"""Stage one server-issued, bounded Apple grant for outbound Mac pickup."""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import UTC, datetime
from typing import cast

from my_pa.application.native_sources import (
    NativeRequestContext,
    NativeSourceController,
    NativeSourceHost,
    NativeSourceStore,
)
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.native_sources import SqlNativeSourceControlStore
from my_pa.infrastructure.persistence.principal_scope import capture_context


class _NoHost:
    def __getattr__(self, name: str) -> object:
        raise RuntimeError(f"remote Apple grant staging cannot call a local host: {name}")


class _NoProposals:
    def open_review_proposals(self, version_ids: tuple[str, ...]) -> tuple[str, ...]:
        del version_ids
        return ()


def _operator_principal(settings: Settings, supplied: str | None) -> str:
    """Resolve the explicit Entra owner or enforce the scratch process pin."""
    admissible = settings.admissible_client_principal_id()
    if admissible is None:
        if supplied is None:
            raise ValueError("Entra grant staging requires --principal-id")
        return validate_identifier(supplied, IdKind.PRINCIPAL)
    if supplied is not None and supplied != admissible:
        raise ValueError("--principal-id does not match the local operator")
    return admissible


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apple-grant", description=__doc__)
    parser.add_argument("--configuration-id", required=True)
    parser.add_argument("--bucket-id", required=True)
    parser.add_argument(
        "--principal-id",
        help="owning Principal; required in Entra mode and pinned in local_operator mode",
    )
    parser.add_argument("--start", required=True, help="inclusive ISO-8601 timestamp")
    parser.add_argument("--end", required=True, help="inclusive ISO-8601 timestamp")
    parser.add_argument("--cursor")
    parser.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    try:
        principal_id = _operator_principal(settings, args.principal_id)
    except ValueError as refusal:
        print(f"refused     {refusal}")
        return 1
    work = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
    audit_engine = create_database_engine(
        settings.parsed_database_url(), statement_timeout_ms=30_000
    )
    try:
        store = SqlNativeSourceControlStore(work, capture_context(principal_id))
        bindings = store.bucket_bindings((args.bucket_id,))
        if len(bindings) != 1:
            raise ValueError("the exact Apple bucket is not registered")
        now = datetime.now(UTC)
        controller = NativeSourceController(
            store=cast(NativeSourceStore, store),
            host=cast(NativeSourceHost, _NoHost()),
            audit=SqlAlchemyAuditSink(audit_engine),
            proposals=_NoProposals(),
        )
        grant = controller.stage_remote_grant(
            NativeRequestContext(
                principal=Principal(principal_id, PrincipalKind.OPERATOR, True),
                purpose=Purpose.SOURCE_INSPECTION,
                correlation_id=issue_identifier(IdKind.CORRELATION),
                request_id=f"apple-{secrets.token_hex(16)}",
                authorized_source_ids=frozenset({bindings[0].source_id}),
                at=now,
            ),
            configuration_id=args.configuration_id,
            bucket_id=args.bucket_id,
            time_range=(datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)),
            cursor=args.cursor,
            limit=args.limit,
        )
    except ValueError as refusal:
        print(f"refused     {refusal}")
        return 1
    finally:
        work.dispose()
        audit_engine.dispose()
    print(f"authority_id     {grant.authority_id}")
    print(f"envelope_id      {grant.envelope_id}")
    print(f"expires          {grant.expires_at_unix_milliseconds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
