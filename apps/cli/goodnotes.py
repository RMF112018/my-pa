"""Operator-only trigger for bounded GoodNotes reconciliation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath

from sqlalchemy.engine import Engine

from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.goodnotes import LocalGoodNotesRuntime, compose_local_goodnotes_runtime
from my_pa.bootstrap.settings import ENV_PREFIX, AuthMode, load_settings
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.infrastructure.database.engine import create_database_engine

EXIT_OK = 0
EXIT_REFUSED = 1


def _runtime() -> LocalGoodNotesRuntime:
    root = os.environ.get(f"{ENV_PREFIX}GOODNOTES_ROOT", "")
    ocr_root = os.environ.get(f"{ENV_PREFIX}GOODNOTES_OCR_ROOT", "")
    executable = os.environ.get(f"{ENV_PREFIX}GOODNOTES_OCR_EXECUTABLE", "")
    arguments = os.environ.get(f"{ENV_PREFIX}GOODNOTES_OCR_ARGUMENTS_JSON", "[]")
    if not root or not ocr_root or not executable:
        raise ValueError(
            "GoodNotes root, OCR root, and OCR executable require explicit operator settings"
        )
    decoded = json.loads(arguments)
    if not isinstance(decoded, list) or not all(isinstance(value, str) for value in decoded):
        raise ValueError("GoodNotes OCR arguments must be a JSON string list")
    return compose_local_goodnotes_runtime(
        admitted_root=Path(root),
        manifest_relative_path=PurePosixPath(
            os.environ.get(f"{ENV_PREFIX}GOODNOTES_MANIFEST", "goodnotes-manifest.json")
        ),
        ocr_command=(executable, *decoded),
        ocr_root=Path(ocr_root),
        ocr_name=os.environ.get(f"{ENV_PREFIX}GOODNOTES_OCR_NAME", "operator_local_ocr"),
        ocr_version=os.environ.get(f"{ENV_PREFIX}GOODNOTES_OCR_VERSION", "1"),
        source_root_id=os.environ.get(f"{ENV_PREFIX}GOODNOTES_SOURCE_ROOT_ID", "goodnotes-local"),
    )


def _engine() -> Engine:
    return create_database_engine(
        load_settings().parsed_database_url(), statement_timeout_ms=30_000
    )


def _operator_principal_id(supplied: str | None) -> str:
    settings = load_settings()
    if settings.auth_mode is not AuthMode.LOCAL_OPERATOR:
        if supplied is None:
            raise ValueError("Entra GoodNotes reconciliation requires --principal-id")
        return validate_identifier(supplied, IdKind.PRINCIPAL)
    principal = local_principal()
    if not principal.is_operator:
        raise ValueError("GoodNotes operator authentication is unavailable")
    if supplied is not None and supplied != principal.principal_id:
        raise ValueError("--principal-id does not match the local operator")
    return principal.principal_id


def _reconcile(args: argparse.Namespace) -> int:
    runtime = _runtime()
    principal_id = _operator_principal_id(args.principal_id)
    liveness_receipts = runtime.observe_liveness(principal_id=principal_id)
    runtime.require_current_liveness(principal_id, liveness_receipts)
    engine = _engine()
    try:
        receipt = runtime.reconcile(
            engine=engine,
            principal_id=principal_id,
            idempotency_key=args.idempotency_key,
            liveness_receipts=liveness_receipts,
        )
    finally:
        engine.dispose()
    print(f"receipt {receipt.receipt_id}")
    print(f"pages {len(receipt.page_version_ids)}")
    print(f"regions {receipt.created_regions}")
    print(f"replayed {str(receipt.replayed).lower()}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="goodnotes", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument(
        "--principal-id",
        help="owning Principal; required in Entra mode and pinned in local_operator mode",
    )
    reconcile.add_argument("--idempotency-key", required=True)
    reconcile.set_defaults(handler=_reconcile)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
