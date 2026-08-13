"""Authentication for the dedicated Apple bridge credential registry."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from hmac import compare_digest

from sqlalchemy import Connection, Engine, select

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.native_apple import AppleBridgeIdentity, AppleMachineCredentialError
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    native_apple_bridge_credentials,
    native_bridges,
)

__all__ = [
    "authenticate_apple_bridge_credential",
    "register_apple_bridge_credential",
    "revoke_apple_bridge_credential",
]


def register_apple_bridge_credential(
    connection: Connection,
    *,
    bridge_id: str,
    secret_sha256: str,
    at: datetime,
    context: PrincipalContext,
) -> str:
    """Store one independently revocable credential for an exact owned bridge."""
    validate_identifier(bridge_id, IdKind.NATIVE_BRIDGE)
    if len(secret_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in secret_sha256
    ):
        raise ValueError("Apple bridge credential digest must be SHA-256")
    owned = connection.execute(
        select(native_bridges.c.bridge_id).where(
            native_bridges.c.bridge_id == bridge_id,
            partition_criterion(native_bridges, context),
        )
    ).scalar_one_or_none()
    if owned is None:
        raise ValueError("the Apple bridge is not registered to this Principal")
    credential_id = issue_identifier(IdKind.APPLE_BRIDGE_CREDENTIAL)
    connection.execute(
        native_apple_bridge_credentials.insert().values(
            principal_bound_values(
                {
                    "credential_id": credential_id,
                    "bridge_id": bridge_id,
                    "secret_sha256": secret_sha256,
                    "state": "active",
                    "created_at": at,
                    "revoked_at": None,
                },
                native_apple_bridge_credentials,
                context,
            )
        )
    )
    return credential_id


def revoke_apple_bridge_credential(
    connection: Connection,
    *,
    credential_id: str,
    at: datetime,
    context: PrincipalContext,
) -> bool:
    if not credential_id.startswith("abcred_") or not 15 <= len(credential_id) <= 72:
        raise ValueError("Apple bridge credential identifier is invalid")
    result = connection.execute(
        native_apple_bridge_credentials.update()
        .where(
            native_apple_bridge_credentials.c.credential_id == credential_id,
            native_apple_bridge_credentials.c.state == "active",
            partition_criterion(native_apple_bridge_credentials, context),
        )
        .values(state="revoked", revoked_at=at)
    )
    return result.rowcount == 1


def authenticate_apple_bridge_credential(
    engine: Engine, presented: str | None
) -> AppleBridgeIdentity:
    """Resolve one active bridge secret without exposing credential-state oracles."""
    prefix = "AppleBridgeCredential "
    if presented is None or not presented.startswith(prefix):
        raise AppleMachineCredentialError()
    credential_id, separator, secret = presented.removeprefix(prefix).partition(":")
    if not separator or not credential_id or not secret:
        raise AppleMachineCredentialError()
    with engine.connect() as connection:
        row = connection.execute(
            select(
                native_apple_bridge_credentials.c.principal_id,
                native_apple_bridge_credentials.c.bridge_id,
                native_apple_bridge_credentials.c.secret_sha256,
                native_apple_bridge_credentials.c.state,
            ).where(native_apple_bridge_credentials.c.credential_id == credential_id)
        ).one_or_none()
    # Perform one digest comparison for both known and unknown identities.
    expected = "0" * 64 if row is None else str(row.secret_sha256)
    valid = compare_digest(sha256(secret.encode()).hexdigest(), expected)
    if row is None or str(row.state) != "active" or not valid:
        raise AppleMachineCredentialError()
    return AppleBridgeIdentity(
        credential_id=credential_id,
        principal_id=str(row.principal_id),
        bridge_id=str(row.bridge_id),
    )
