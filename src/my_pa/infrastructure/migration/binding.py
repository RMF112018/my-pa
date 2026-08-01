"""What a run is bound to, and the check that it still holds.

A run names one source file and one target schema revision. HZ-SRC-DRIFT and
HZ-TGT-DRIFT are the hazard that either changes underneath a partially completed
load: rows already written would then describe a source that no longer exists,
and the resume point would be a guess. So the binding is recorded at
``init-run`` and recomputed on every subsequent command. Any mismatch stops the
run; nothing is repaired, adjusted, or continued on a hope.

The source digest is the whole file, not a sample. A 4.4 GB read takes seconds
and is the only evidence that the bytes are the bytes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, text

from my_pa.infrastructure.migration.reader import SourceError, open_source, schema_version

#: Large enough that the read is sequential, small enough to stay off the heap.
_DIGEST_CHUNK_BYTES = 1 << 20


class DriftError(RuntimeError):
    """The bound source or target no longer matches the run. Fail closed."""


@dataclass(frozen=True)
class RunBinding:
    """The three facts a run is pinned to."""

    source_path: Path
    source_sha256: str
    source_bytes: int
    source_schema_version: int
    target_alembic_revision: str

    def verify(self, observed: RunBinding) -> None:
        """Raise if `observed` differs on any bound fact.

        The path is deliberately not compared: the same bytes under a different
        path are the same source, and the digest is what proves it.
        """
        mismatches = [
            name
            for name in (
                "source_sha256",
                "source_bytes",
                "source_schema_version",
                "target_alembic_revision",
            )
            if getattr(self, name) != getattr(observed, name)
        ]
        if mismatches:
            raise DriftError(
                "HZ-SRC-DRIFT: the run's bound identity no longer matches; "
                f"changed: {', '.join(mismatches)}"
            )


def file_digest(path: Path) -> tuple[str, int]:
    """Return the SHA-256 and byte length of `path`."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_DIGEST_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def target_revision(connection: Connection) -> str:
    """Return the Alembic revision the target database is at."""
    revisions = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars()
    heads = sorted(str(revision) for revision in revisions)
    if len(heads) != 1:
        raise DriftError(
            f"HZ-TGT-DRIFT: the target database reports {len(heads)} Alembic revisions, not one"
        )
    return heads[0]


def observe(source_path: Path, connection: Connection) -> RunBinding:
    """Measure the current source file and target revision."""
    sha256, size = file_digest(source_path)
    with open_source(source_path) as source:
        version = schema_version(source)
    if size == 0:
        raise SourceError(f"source database at {source_path} is empty")
    return RunBinding(
        source_path=source_path,
        source_sha256=sha256,
        source_bytes=size,
        source_schema_version=version,
        target_alembic_revision=target_revision(connection),
    )
