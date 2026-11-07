"""Shared root and anchored-syscall helpers of the report content root (WP06 T13).

Used by `filesystem.FilesystemReportContentStore` and
`staging.FilesystemReportTransferStaging`, which live under the same
configured root: the root's resolution and overlap refusals, the open flags
every directory-anchored syscall uses, and whether the platform has them.
Extracted unchanged from `filesystem.py` (WP05 C2); no message carries a path.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Final

__all__ = [
    "ANCHORING_IS_AVAILABLE",
    "CREATE_FLAGS",
    "DIRECTORY_FLAGS",
    "READ_FLAGS",
    "ReportContentRootError",
    "close",
    "resolve_clear_root",
]


class ReportContentRootError(Exception):
    """The configured report content root is unusable, or overlaps a root it must avoid.

    A configuration defect, raised at construction (composition refuses to
    start), never a request-time answer. Names no path.
    """


_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY_FLAGS: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW
CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
READ_FLAGS: Final = os.O_RDONLY | _NOFOLLOW

ANCHORING_IS_AVAILABLE: Final = all(
    call in os.supports_dir_fd for call in (os.open, os.link, os.unlink, os.mkdir, os.rmdir)
)


def _resolved_directory(candidate: Path) -> Path:
    try:
        if candidate.is_symlink():
            raise ReportContentRootError("the configured report content root is a symbolic link")
        resolved = candidate.resolve(strict=True)
    except ReportContentRootError:
        raise
    except (OSError, RuntimeError):
        raise ReportContentRootError(
            "the configured report content root could not be resolved"
        ) from None
    if not resolved.is_dir():
        raise ReportContentRootError(
            "the configured report content root is not an existing directory"
        )
    return resolved


def _comparable(path: Path) -> Path:
    """A root to stay clear of, resolved; an unresolvable one compared as configured."""
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return Path(path).absolute()


def _overlaps(one: Path, other: Path) -> bool:
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


def resolve_clear_root(
    root: Path,
    *,
    source_roots: Iterable[Path] = (),
    managed_documents_root: Path | None = None,
    other_roots: Iterable[Path] = (),
) -> Path:
    """`root` resolved; refused if missing, not a directory, a link, or overlapping a root."""
    resolved = _resolved_directory(Path(root))
    avoided = [*source_roots, *other_roots]
    if managed_documents_root is not None:
        avoided.append(managed_documents_root)
    for other in avoided:
        if _overlaps(resolved, _comparable(Path(other))):
            raise ReportContentRootError(
                "the report content root is the same tree as a root it must stay "
                "clear of, or lies inside one, or contains one -- a configured "
                "source root, the managed document root, or (for a backup) the "
                "live report content root"
            )
    return resolved


def close(descriptor: int | None) -> None:
    if descriptor is not None:
        os.close(descriptor)
