#!/usr/bin/env python3
"""Prove the pinned PostgreSQL child belongs to the pinned 17.10 index."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

INDEX_DIGEST = "sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317"
CHILD_DIGEST = "sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify-postgres-index.py RAW_INDEX_JSON", file=sys.stderr)
        return 64
    raw = Path(sys.argv[1]).read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != INDEX_DIGEST:
        print("PostgreSQL 17.10 parent index digest mismatch", file=sys.stderr)
        return 1
    index = json.loads(raw)
    matches = [
        manifest
        for manifest in index.get("manifests", [])
        if manifest.get("platform") == {"architecture": "amd64", "os": "linux"}
    ]
    if len(matches) != 1 or matches[0].get("digest") != CHILD_DIGEST:
        print("PostgreSQL 17.10 linux/amd64 child digest mismatch", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
