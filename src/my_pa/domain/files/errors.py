"""Typed refusals of the pure file workspace domain.

Each names the field and a closed token and never the value it refused, the
discipline `domain.reports.errors` applies: a refusal can be mapped to a public
code without stripping anything from its message, and neither its message nor
its `repr` can echo a path, a name, a token or content.
"""

from __future__ import annotations

from my_pa.domain.files.vocabulary import FilesReason

__all__ = [
    "FilesArgumentError",
    "FilesDomainError",
    "FilesRefusal",
    "RangeNotSatisfiableError",
]


class FilesDomainError(Exception):
    """A file workspace value refused to exist."""

    def __init__(self, field: str, code: str) -> None:
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.field!r}, {self.code!r})"


class FilesRefusal(FilesDomainError):  # noqa: N818 - contract section 7 vocabulary
    """A refusal carrying one of the contract's section 7 reason tokens."""

    def __init__(self, field: str, reason: FilesReason) -> None:
        super().__init__(field, FilesReason(reason).value)
        self.reason = FilesReason(reason)


class FilesArgumentError(FilesDomainError):
    """A non-path argument broke its shape: `code` is `type`, `pattern` or `bounds`.

    Section 7 has no reason token for these (they are ordinary request
    validation); the application maps them to `invalid_request`.
    """


class RangeNotSatisfiableError(FilesDomainError):
    """A well-formed `Range` the file cannot satisfy: HTTP 416, no reason token."""

    def __init__(self) -> None:
        super().__init__("Range", "unsatisfiable")
