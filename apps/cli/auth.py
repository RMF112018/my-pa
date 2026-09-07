"""Operator-only bootstrap and recovery grant administration.

The command never accepts a Principal to act as. Every grant targets the fixed
LOCAL_OPERATOR_UUID, is printed once, and is stored only as a SHA-256 digest.
Mutations require explicit non-secret assertions about the configured target
and an exact operation confirmation. The database URL is read from
MY_PA_DATABASE_URL only; it is never an argument and never printed.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.identity.auth_grants import AuthGrantPurpose
from my_pa.domain.identity.auth_state import AuthStateKind
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.auth_grants import AuthGrantStore
from my_pa.infrastructure.persistence.auth_state import AuthStateValidator

EXIT_OK = 0
EXIT_REFUSED = 1
PRODUCTION_RP_ID = "pa.bobby-fetting.me"
PRODUCTION_ORIGIN = "https://pa.bobby-fetting.me"
ISSUE_CONFIRMATION = {
    "bootstrap": "ISSUE_BOOTSTRAP_GRANT",
    "recovery": "ISSUE_OPERATOR_RECOVERY_GRANT",
}
REVOKE_CONFIRMATION = {
    "bootstrap": "REVOKE_BOOTSTRAP_GRANT",
    "recovery": "REVOKE_OPERATOR_RECOVERY_GRANT",
}


class TargetMismatchError(ValueError):
    """The explicit target assertions do not identify this configured runtime."""


def _purpose(plane: str) -> AuthGrantPurpose:
    return (
        AuthGrantPurpose.BOOTSTRAP if plane == "bootstrap" else AuthGrantPurpose.OPERATOR_RECOVERY
    )


def _assert_confirmation(args: argparse.Namespace) -> None:
    """Refuse issue/revoke unless the exact non-boolean confirmation is present."""
    if args.action == "status":
        return
    expected = (
        ISSUE_CONFIRMATION[args.plane]
        if args.action == "issue"
        else REVOKE_CONFIRMATION[args.plane]
    )
    presented = args.confirm_issue if args.action == "issue" else args.confirm_revoke
    if presented != expected:
        raise TargetMismatchError("operation confirmation does not match")


def _assert_configured_target(settings: Settings, args: argparse.Namespace) -> None:
    """Compare assertions to parsed settings before any engine is created."""
    configured = settings.parsed_database_url()
    if (
        args.expected_host != configured.host
        or args.expected_port != (configured.port or 5432)
        or args.expected_database != configured.database
        or args.expected_local_principal != str(LOCAL_OPERATOR_UUID)
    ):
        raise TargetMismatchError("configured database or Principal does not match the assertions")
    if args.expected_rp_id != PRODUCTION_RP_ID or args.expected_origin != PRODUCTION_ORIGIN:
        raise TargetMismatchError("configured WebAuthn relying party does not match production")
    relying_party = settings.webauthn_relying_party()
    if (
        relying_party is None
        or relying_party.rp_id != args.expected_rp_id
        or not relying_party.accepts_origin(args.expected_origin)
    ):
        raise TargetMismatchError("configured WebAuthn relying party does not match production")


def _assert_connected_identity(connection: Connection, args: argparse.Namespace) -> None:
    """Re-check catalog name and Alembic head on the live connection."""
    database = connection.execute(text("SELECT current_database()")).scalar_one()
    try:
        revisions = (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        )
    except ProgrammingError as error:
        raise TargetMismatchError(
            "connected database identity or migration head does not match"
        ) from error
    if (
        database != args.expected_database
        or len(revisions) != 1
        or revisions[0] != args.expected_alembic_head
    ):
        raise TargetMismatchError("connected database identity or migration head does not match")


def _status(connection: Connection, args: argparse.Namespace, now: datetime) -> int:
    state = AuthStateValidator(connection).inspect(now=now)
    active = AuthGrantStore(connection).active(_purpose(args.plane), now=now)
    print(f"state            {state.kind.value}")
    print(f"reason           {','.join(reason.value for reason in state.reasons)}")
    print(f"grant            {'active' if active is not None else 'absent'}")
    if active is not None:
        print(f"expires          {active.expires_at.isoformat()}")
    return EXIT_OK


def _issue(connection: Connection, args: argparse.Namespace, now: datetime) -> int:
    purpose = _purpose(args.plane)
    expected_state = (
        AuthStateKind.UNINITIALIZED
        if purpose is AuthGrantPurpose.BOOTSTRAP
        else AuthStateKind.READY
    )
    state = AuthStateValidator(connection).inspect(now=now)
    if state.kind is not expected_state:
        raise TargetMismatchError(f"auth state does not permit {purpose.value} grant issuance")
    issued = AuthGrantStore(connection).issue(purpose, now=now)
    print(f"purpose          {purpose.value}")
    print(f"expires          {issued.record.expires_at.isoformat()}")
    print(f"grant            {issued.raw_grant}")
    print("notice           shown once; only its SHA-256 digest is stored")
    return EXIT_OK


def _revoke(connection: Connection, args: argparse.Namespace, now: datetime) -> int:
    purpose = _purpose(args.plane)
    if not AuthGrantStore(connection).revoke_active(purpose, now=now):
        raise TargetMismatchError("no unconsumed grant exists for this purpose")
    print(f"purpose          {purpose.value}")
    print("state            revoked")
    return EXIT_OK


def _run(args: argparse.Namespace) -> int:
    _assert_confirmation(args)
    settings = load_settings()
    _assert_configured_target(settings, args)
    engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
    try:
        with engine.begin() as connection:
            _assert_connected_identity(connection, args)
            now = datetime.now(UTC)
            if args.action == "status":
                return _status(connection, args, now)
            if args.action == "issue":
                return _issue(connection, args, now)
            return _revoke(connection, args, now)
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auth", description=__doc__)
    parser.add_argument("plane", choices=("bootstrap", "recovery"))
    parser.add_argument("action", choices=("status", "issue", "revoke"))
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-port", required=True, type=int)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-alembic-head", required=True)
    parser.add_argument("--expected-rp-id", required=True)
    parser.add_argument("--expected-origin", required=True)
    parser.add_argument("--expected-local-principal", required=True)
    parser.add_argument(
        "--confirm-issue",
        default=None,
        metavar="TOKEN",
        help="ISSUE_BOOTSTRAP_GRANT or ISSUE_OPERATOR_RECOVERY_GRANT",
    )
    parser.add_argument(
        "--confirm-revoke",
        default=None,
        metavar="TOKEN",
        help="REVOKE_BOOTSTRAP_GRANT or REVOKE_OPERATOR_RECOVERY_GRANT",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (TargetMismatchError, ValueError) as refusal:
        print(f"refused          {refusal}")
        return EXIT_REFUSED
    except OperationalError:
        print("refused          database target is unreachable")
        return EXIT_REFUSED
    except SQLAlchemyError:
        print("refused          database target is unavailable")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
