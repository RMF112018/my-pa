"""Read and write the generated DDL as reviewable ``.sql`` files.

The revisions execute these files rather than embedding the statements, and the
generator regenerates them from the source profile. The profile itself is 4.3 MB
and stays out of the repository, so the checked-in SQL is what review and
``alembic upgrade`` actually see.

Statements are stored one per paragraph, each terminated by ``;``. A statement
may not contain a ``;`` of its own, which is asserted on write, so splitting is
exact rather than a guess about SQL lexing.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

_SEPARATOR = ";\n\n"


class SqlFileError(RuntimeError):
    """A statement cannot be stored or recovered unambiguously."""


def write_statements(path: Path, statements: Sequence[str]) -> None:
    """Write ``statements`` to ``path``, one per paragraph."""
    bodies = []
    for statement in statements:
        body = statement.rstrip().rstrip(";").rstrip()
        if ";" in body:
            raise SqlFileError(f"statement contains an embedded ';': {body[:80]!r}")
        bodies.append(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _SEPARATOR.join(bodies) + ";\n" if bodies else ""
    path.write_text(text, encoding="utf-8")


def read_statements(path: Path) -> tuple[str, ...]:
    """Read the statements written by :func:`write_statements`."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return ()
    return tuple(f"{part.strip()};" for part in text.rstrip(";").split(_SEPARATOR) if part.strip())
