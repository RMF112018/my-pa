#!/usr/bin/env python3
"""Verify the canonical immutable PostgreSQL backup runtime attestation."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def main() -> int:
    writer = Path(__file__).with_name("write-postgres-backup-runtime-attestation.py")
    spec = importlib.util.spec_from_file_location("postgres_backup_runtime_attestation", writer)
    if spec is None or spec.loader is None:
        print("PostgreSQL backup runtime attestation refused: verifier unavailable")
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors = module.verify()
    if errors:
        print("PostgreSQL backup runtime attestation refused: " + ", ".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
