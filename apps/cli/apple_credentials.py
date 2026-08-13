"""Operator-only minting for independently revocable Apple bridge credentials."""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import UTC, datetime
from hashlib import sha256

from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.apple_bridge_credentials import (
    register_apple_bridge_credential,
    revoke_apple_bridge_credential,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context


def _operator_principal(settings: Settings, supplied: str | None) -> str:
    """Resolve the explicit Entra owner or enforce the scratch process pin."""
    admissible = settings.admissible_client_principal_id()
    if admissible is None:
        if supplied is None:
            raise ValueError("Entra credential administration requires --principal-id")
        return validate_identifier(supplied, IdKind.PRINCIPAL)
    if supplied is not None and supplied != admissible:
        raise ValueError("--principal-id does not match the local operator")
    return admissible


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apple-credentials", description=__doc__)
    parser.add_argument(
        "--principal-id",
        help="owning Principal; required in Entra mode and pinned in local_operator mode",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--bridge-id", required=True)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--credential-id", required=True)
    args = parser.parse_args(argv)
    settings = load_settings()
    try:
        principal_id = _operator_principal(settings, args.principal_id)
    except ValueError as refusal:
        print(f"refused     {refusal}")
        return 1
    engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
    try:
        with engine.begin() as connection:
            if args.command == "revoke":
                changed = revoke_apple_bridge_credential(
                    connection,
                    credential_id=args.credential_id,
                    at=datetime.now(UTC),
                    context=capture_context(principal_id),
                )
                if not changed:
                    raise ValueError("no active credential of this Principal has that identifier")
                credential_id = args.credential_id
                secret = ""
            else:
                secret = secrets.token_urlsafe(32)
                credential_id = register_apple_bridge_credential(
                    connection,
                    bridge_id=args.bridge_id,
                    secret_sha256=sha256(secret.encode()).hexdigest(),
                    at=datetime.now(UTC),
                    context=capture_context(principal_id),
                )
    except ValueError as refusal:
        print(f"refused     {refusal}")
        return 1
    finally:
        engine.dispose()
    if args.command == "revoke":
        print(f"credential_id    {credential_id}")
        print("state            revoked")
    else:
        print(f"credential       {credential_id}:{secret}")
        print("notice           shown once; present with Authorization: AppleBridgeCredential")
    return 0


if __name__ == "__main__":
    sys.exit(main())
