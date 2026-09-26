"""Operator administration for durable remote MCP clients and kill switches.

The three `profile-*` commands speak the `chatllm-profile-cli-v1` JSON
contract: a deterministic document whose top-level keys are always
`schema_version, command, profile_version, target, eligibility, gates, pre,
post, applied, committed, converged, rolled_back, failure`. The document never
carries a raw OAuth client ID, a raw resource/audience, a raw grant UUID, a
token, a secret, or personal data — client, resource, and existing grant rows
are named only by `sha256:` fingerprints.

`profile-apply` is atomic: it runs inside one `engine.begin()` transaction,
locks the `remote_clients` row `FOR UPDATE`, re-reads grants after the lock,
mutates in REVOKE then RENEW then ADD phase order, re-reads and recomputes
after mutation, and raises a dedicated convergence exception unless the
post-apply state has no blockers, no pending revoke/renew/add, exactly one
canonical durable active grant per desired capability, and no extra
profile-owned active grant. The exception rolls the transaction back and the
CLI emits a rollback document (`rolled_back=true`). Success JSON is printed
only after the transaction commits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Row

from my_pa.application.chatllm_data_profile import (
    ChatLLMCondition,
    ChatLLMConditionCode,
    ChatLLMGrantAction,
    ChatLLMGrantRecord,
    ChatLLMProfilePlan,
    parse_grant_record,
    plan_profile_state,
)
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.gateway import application_composition_state
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.identity.chatllm_capability_policy import CHATLLM_DATA_PROFILE_VERSION
from my_pa.domain.identity.operation import REMOTE_CAPABILITY_VERSION, Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_capability_grants,
    remote_security_controls,
)

SCHEMA_VERSION = "chatllm-profile-cli-v1"

_PHASE_ORDER: tuple[str, ...] = ("revoke", "renew", "add", "noop")
_SEVERITY_ORDER: tuple[str, ...] = ("blocking", "drift", "warning")

#: Condition codes that mean an extra profile-owned grant is active. Any of
#: these in the post-apply plan means the apply did not converge.
_EXTRA_ACTIVE_CODES: frozenset[ChatLLMConditionCode] = frozenset(
    {
        ChatLLMConditionCode.ACTIVE_PURPOSE_MISMATCH,
        ChatLLMConditionCode.ACTIVE_WRITE_CLASS_MISMATCH,
        ChatLLMConditionCode.EXTRA_ACTIVE_VARIANT,
        ChatLLMConditionCode.OUT_OF_PROFILE_ACTIVE_RESOURCE,
        ChatLLMConditionCode.OUT_OF_PROFILE_ACTIVE_SCOPE,
        ChatLLMConditionCode.UNSUPPORTED_ACTIVE_VERSION,
        ChatLLMConditionCode.DUPLICATE_CANONICAL_ACTIVE,
        ChatLLMConditionCode.UNEXPECTED_CONTROL_PLANE_AUTHORITY,
        ChatLLMConditionCode.UNEXPECTED_ODR_AUTHORITY,
        ChatLLMConditionCode.UNMANAGED_ACTIVE_ROW,
        ChatLLMConditionCode.ACTIVE_COMPATIBILITY_ONLY,
        ChatLLMConditionCode.UNEXPECTED_UNCOMPOSED_DATA_GRANT,
    }
)


class ProfileConvergenceError(RuntimeError):
    """Post-mutation or blocker verification failed; the apply must roll back."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProfileApplyError(RuntimeError):
    """Apply failed and the transaction rolled back; carries the rollback JSON."""

    def __init__(self, *, reason: str, exit_code: int, payload: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code
        self.payload = payload


class _ProfileResult(NamedTuple):
    exit_code: int
    payload: dict[str, Any] | None
    rollback_payload: dict[str, Any] | None = None


def _uuid(value: str) -> UUID:
    return UUID(value)


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include an offset or Z")
    return parsed.astimezone(UTC)


def _fingerprint(value: str) -> str:
    """`sha256:` fingerprint of a raw value; the raw value is never emitted."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _grant_ref(grant_id: UUID | None) -> str | None:
    """Fingerprint of an existing grant row's textual UUID; `None` for a new row."""
    if grant_id is None:
        return None
    return _fingerprint(str(grant_id))


def _emit(payload: dict[str, Any]) -> str:
    """Deterministic JSON preserving the required top-level key order."""
    return json.dumps(payload, indent=2)


def _add_profile_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--oauth-client-id", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument(
        "--profile-version",
        required=True,
        help="must match the repository ChatLLM data profile version",
    )


def _grant_records(rows: tuple[Row[Any], ...]) -> tuple[ChatLLMGrantRecord, ...]:
    """Parse every grant row, including unknown capability/purpose values."""
    return tuple(
        parse_grant_record(
            capability_raw=row.capability,
            capability_version=row.capability_version,
            purpose_raw=row.purpose,
            is_write=bool(row.is_write),
            resource=row.resource,
            scope=row.external_scope,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            grant_id=row.id,
        )
        for row in rows
    )


def _sort_conditions(
    conditions: tuple[ChatLLMCondition, ...],
) -> tuple[ChatLLMCondition, ...]:
    return tuple(
        sorted(
            conditions,
            key=lambda item: (
                item.capability,
                _SEVERITY_ORDER.index(item.severity),
                item.code.value,
                tuple(_grant_ref(grant_id) or "" for grant_id in item.grant_ids),
            ),
        )
    )


def _sort_actions(actions: tuple[ChatLLMGrantAction, ...]) -> tuple[ChatLLMGrantAction, ...]:
    return tuple(
        sorted(
            actions,
            key=lambda item: (
                _PHASE_ORDER.index(item.kind),
                item.capability.value if item.capability is not None else item.capability_raw,
                item.purpose.value if item.purpose is not None else "",
                _grant_ref(item.grant_id) or "",
            ),
        )
    )


def _condition_json(condition: ChatLLMCondition) -> dict[str, Any]:
    return {
        "capability": condition.capability,
        "code": condition.code.value,
        "severity": condition.severity,
        "count": len(condition.grant_ids),
        "grant_refs": sorted(
            ref for ref in (_grant_ref(grant_id) for grant_id in condition.grant_ids) if ref
        ),
    }


def _action_json(action: ChatLLMGrantAction) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "capability": (
            action.capability.value if action.capability is not None else action.capability_raw
        ),
        "purpose": action.purpose.value if action.purpose is not None else None,
        "is_write": action.is_write,
        "grant_ref": _grant_ref(action.grant_id),
    }


def _snapshot(plan: ChatLLMProfilePlan) -> dict[str, Any]:
    conditions = _sort_conditions(plan.conditions)
    actions = _sort_actions(plan.actions)
    return {
        "healthy": plan.healthy,
        "desired_effective_count": len(plan.desired_effective),
        "desired_effective": sorted(item.value for item in plan.desired_effective),
        "conditions": [_condition_json(item) for item in conditions],
        "actions": [_action_json(item) for item in actions],
        "counts": {
            "add": sum(1 for item in actions if item.kind == "add"),
            "renew": sum(1 for item in actions if item.kind == "renew"),
            "revoke": sum(1 for item in actions if item.kind == "revoke"),
            "noop": sum(1 for item in actions if item.kind == "noop"),
            "blocking": sum(1 for item in conditions if item.severity == "blocking"),
        },
    }


def _target(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "client_fingerprint": _fingerprint(args.oauth_client_id),
        "resource_fingerprint": _fingerprint(args.resource),
        "scope": args.scope,
        "capability_version": REMOTE_CAPABILITY_VERSION,
    }


def _eligibility(
    *,
    client: Row[Any] | None,
    settings: Settings,
    scope: str,
    resource: str,
    now: datetime,
) -> dict[str, Any]:
    blockers: list[str] = []
    if client is None:
        blockers.append("CLIENT_NOT_FOUND")
    else:
        if not client.enabled:
            blockers.append("CLIENT_DISABLED")
        if client.revoked_at is not None:
            blockers.append("CLIENT_REVOKED")
        expires_at = client.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at is not None and expires_at <= now:
            blockers.append("CLIENT_EXPIRED")
        if scope not in set(client.registered_scopes.split()):
            blockers.append("SCOPE_NOT_REGISTERED")
        if scope not in set(settings.oauth_scopes.split()):
            blockers.append("SCOPE_UNSUPPORTED")
        if resource != settings.oauth_audience:
            blockers.append("RESOURCE_MISMATCH")
        if not settings.mcp_chatllm_gateway_enabled:
            blockers.append("GATEWAY_DISABLED")
        if client.oauth_client_id not in settings.chatllm_gateway_oauth_client_id_set():
            blockers.append("CLIENT_NOT_ALLOWLISTED")
    inspectable = client is not None
    return {
        "inspectable": inspectable,
        "apply_eligible": inspectable and not blockers,
        "blockers": sorted(blockers),
    }


def _gates(
    repository: RemoteIdentityRepository,
    settings: Settings,
    client: Row[Any] | None,
) -> dict[str, Any]:
    controls = repository.get_security_controls()
    remote_enabled = bool(controls is not None and controls.remote_enabled)
    global_writes = bool(controls is not None and controls.writes_enabled)
    client_writes = bool(client is not None and client.writes_enabled)
    process_writes = settings.remote_writes_enabled
    return {
        "process_remote_writes_enabled": process_writes,
        "client_writes_enabled": client_writes,
        "global_remote_writes_enabled": global_writes,
        "remote_enabled": remote_enabled,
        "runtime_writes_effective": (
            process_writes and client_writes and global_writes and remote_enabled
        ),
    }


def _payload(
    *,
    command: str,
    profile_version: str,
    target: dict[str, Any],
    eligibility: dict[str, Any],
    gates: dict[str, Any],
    pre: dict[str, Any],
    post: dict[str, Any] | None,
    applied: bool,
    committed: bool,
    converged: bool,
    rolled_back: bool,
    failure: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "profile_version": profile_version,
        "target": target,
        "eligibility": eligibility,
        "gates": gates,
        "pre": pre,
        "post": post,
        "applied": applied,
        "committed": committed,
        "converged": converged,
        "rolled_back": rolled_back,
        "failure": failure,
    }


def _rollback_payload(
    *,
    profile_version: str,
    target: dict[str, Any],
    eligibility: dict[str, Any],
    gates: dict[str, Any],
    pre: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return _payload(
        command="profile-apply",
        profile_version=profile_version,
        target=target,
        eligibility=eligibility,
        gates=gates,
        pre=pre,
        post=None,
        applied=False,
        committed=False,
        converged=False,
        rolled_back=True,
        failure=reason,
    )


def _resolve_client(repository: RemoteIdentityRepository, oauth_client_id: str) -> Row[Any] | None:
    return repository.lock_client_for_update(oauth_client_id=oauth_client_id)


def _compute_plan(
    repository: RemoteIdentityRepository,
    settings: Settings,
    args: argparse.Namespace,
    now: datetime,
    remote_client_id: UUID,
) -> ChatLLMProfilePlan:
    implemented = frozenset(_HANDLERS)
    state = application_composition_state(settings)
    grants = _grant_records(repository.list_capability_grants(remote_client_id=remote_client_id))
    return plan_profile_state(
        implemented=implemented,
        state=state,
        grants=grants,
        now=now,
        resource=args.resource,
        scope=args.scope,
    )


def _assert_converged(plan: ChatLLMProfilePlan) -> None:
    """Require the exact post-apply state; raise so the transaction rolls back."""
    if not plan.healthy:
        raise ProfileConvergenceError("post-apply plan is not healthy")
    for capability in sorted(plan.desired_effective, key=lambda item: item.value):
        durable = [
            condition
            for condition in plan.conditions
            if condition.capability == capability.value
            and condition.code is ChatLLMConditionCode.GRANTED_CANONICAL_DURABLE
        ]
        if len(durable) != 1 or len(durable[0].grant_ids) != 1:
            raise ProfileConvergenceError(
                f"{capability.value} does not have exactly one canonical durable active grant"
            )
    for condition in plan.conditions:
        if condition.code in _EXTRA_ACTIVE_CODES:
            raise ProfileConvergenceError(
                f"extra profile-owned active grant for {condition.capability}"
            )


def _run_profile_apply(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    repository: RemoteIdentityRepository,
    settings: Settings,
    now: datetime,
) -> _ProfileResult:
    if args.profile_version != CHATLLM_DATA_PROFILE_VERSION:
        parser.error(
            f"profile version must be {CHATLLM_DATA_PROFILE_VERSION}; got {args.profile_version}"
        )
    if not args.apply:
        parser.error("profile-apply requires --apply after reviewing profile-plan")
    client = _resolve_client(repository, args.oauth_client_id)
    if client is None:
        parser.error("remote client not found")
    eligibility = _eligibility(
        client=client, settings=settings, scope=args.scope, resource=args.resource, now=now
    )
    gates = _gates(repository, settings, client)
    target = _target(args)
    if not eligibility["apply_eligible"]:
        plan = _compute_plan(repository, settings, args, now, client.id)
        pre = _snapshot(plan)
        payload = _payload(
            command="profile-apply",
            profile_version=args.profile_version,
            target=target,
            eligibility=eligibility,
            gates=gates,
            pre=pre,
            post=None,
            applied=False,
            committed=False,
            converged=False,
            rolled_back=False,
            failure=None,
        )
        return _ProfileResult(1, payload)
    locked = repository.lock_client_for_update(oauth_client_id=args.oauth_client_id)
    if locked is None:
        parser.error("remote client not found")
    plan = _compute_plan(repository, settings, args, now, locked.id)
    pre = _snapshot(plan)
    rollback_payload = _rollback_payload(
        profile_version=args.profile_version,
        target=target,
        eligibility=eligibility,
        gates=gates,
        pre=pre,
        reason="unexpected database or internal error",
    )
    try:
        if plan.blockers:
            # Zero mutation: a blocker means the apply cannot converge, so the
            # post-apply verification below must fail and roll the transaction
            # back rather than commit a partial state.
            _assert_converged(plan)
        if plan.healthy:
            payload = _payload(
                command="profile-apply",
                profile_version=args.profile_version,
                target=target,
                eligibility=eligibility,
                gates=gates,
                pre=pre,
                post=pre,
                applied=True,
                committed=True,
                converged=True,
                rolled_back=False,
                failure=None,
            )
            return _ProfileResult(0, payload, rollback_payload)
        for action in plan.actions:
            if action.kind != "revoke":
                continue
            if action.grant_id is None or not repository.revoke_capability_grant(
                grant_id=action.grant_id,
                remote_client_id=locked.id,
                now=now,
            ):
                raise ProfileConvergenceError(f"revoke failed for {action.capability_raw}")
        for action in plan.actions:
            if action.kind != "renew":
                continue
            if (
                action.grant_id is None
                or action.capability is None
                or not repository.renew_canonical_grant(
                    grant_id=action.grant_id,
                    remote_client_id=locked.id,
                    external_scope=args.scope,
                    capability=action.capability,
                    capability_version=REMOTE_CAPABILITY_VERSION,
                    purpose=action.purpose,
                    resource=args.resource,
                    is_write=action.is_write,
                )
            ):
                raise ProfileConvergenceError(f"renew failed for {action.capability_raw}")
        for action in plan.actions:
            if action.kind != "add":
                continue
            if action.capability is None:
                raise ProfileConvergenceError(f"add without capability for {action.capability_raw}")
            repository.grant(
                remote_client_id=locked.id,
                external_scope=args.scope,
                capability=action.capability,
                now=now,
                is_write=action.is_write,
                resource=args.resource,
                expires_at=None,
                purpose=action.purpose,
            )
        post_plan = _compute_plan(repository, settings, args, now, locked.id)
        _assert_converged(post_plan)
        post = _snapshot(post_plan)
        payload = _payload(
            command="profile-apply",
            profile_version=args.profile_version,
            target=target,
            eligibility=eligibility,
            gates=gates,
            pre=pre,
            post=post,
            applied=True,
            committed=True,
            converged=True,
            rolled_back=False,
            failure=None,
        )
        return _ProfileResult(0, payload, rollback_payload)
    except ProfileConvergenceError as error:
        raise ProfileApplyError(
            reason=error.reason,
            exit_code=1,
            payload=_rollback_payload(
                profile_version=args.profile_version,
                target=target,
                eligibility=eligibility,
                gates=gates,
                pre=pre,
                reason=error.reason,
            ),
        ) from error
    except Exception as error:
        raise ProfileApplyError(
            reason=f"unexpected {type(error).__name__}",
            exit_code=3,
            payload=_rollback_payload(
                profile_version=args.profile_version,
                target=target,
                eligibility=eligibility,
                gates=gates,
                pre=pre,
                reason=f"unexpected {type(error).__name__}",
            ),
        ) from error


def _run_profile_command(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    repository: RemoteIdentityRepository,
    settings: Settings,
    now: datetime,
) -> _ProfileResult:
    if args.command == "profile-apply":
        return _run_profile_apply(parser, args, repository, settings, now)
    if args.profile_version != CHATLLM_DATA_PROFILE_VERSION:
        parser.error(
            f"profile version must be {CHATLLM_DATA_PROFILE_VERSION}; got {args.profile_version}"
        )
    client = _resolve_client(repository, args.oauth_client_id)
    if client is None:
        parser.error("remote client not found")
    eligibility = _eligibility(
        client=client, settings=settings, scope=args.scope, resource=args.resource, now=now
    )
    gates = _gates(repository, settings, client)
    target = _target(args)
    plan = _compute_plan(repository, settings, args, now, client.id)
    pre = _snapshot(plan)
    converged = pre["healthy"] and eligibility["apply_eligible"]
    payload = _payload(
        command=args.command,
        profile_version=args.profile_version,
        target=target,
        eligibility=eligibility,
        gates=gates,
        pre=pre,
        post=None,
        applied=False,
        committed=False,
        converged=converged,
        rolled_back=False,
        failure=None,
    )
    return _ProfileResult(0 if converged else 1, payload)


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
    result: _ProfileResult | None = None
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
                client = repository.lock_client_for_update(oauth_client_id=args.oauth_client_id)
                if client is None:
                    parser.error("remote client not found")
                identifier = repository.grant(
                    remote_client_id=client.id,
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
                row = connection.execute(
                    select(remote_capability_grants.c.remote_client_id).where(
                        remote_capability_grants.c.id == args.grant_uuid
                    )
                ).one_or_none()
                if row is None:
                    parser.error("remote grant not found")
                client = repository.lock_client_for_update_by_id(
                    remote_client_id=row.remote_client_id
                )
                if client is None:
                    parser.error("remote client not found")
                if not repository.revoke_capability_grant(
                    grant_id=args.grant_uuid,
                    remote_client_id=row.remote_client_id,
                    now=now,
                ):
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
                result = _run_profile_command(parser, args, repository, settings, now)
    except ProfileApplyError as error:
        print(_emit(error.payload))
        return error.exit_code
    except Exception:
        if result is not None and result.rollback_payload is not None:
            print(_emit(result.rollback_payload))
            return 3
        raise
    finally:
        engine.dispose()
    if result is not None:
        if result.payload is not None:
            print(_emit(result.payload))
        return result.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
