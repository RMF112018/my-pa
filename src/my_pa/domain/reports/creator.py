"""Who wrote a general report: a server-derived, pseudonymous creator (WP05 A1).

A report root records its creator and every version its author as a
`ReportCreator`: a `CreatorKind` and a `creator_id` derived here from the
authenticated caller, never supplied by one. The application derives the
subject from the Authorization alone (`remote_client` with the authenticated
OAuth client id; `local_principal` with the principal id) and calls
`derive_creator`.

`creator_id` is `gcrt_` and the first 40 hex digits of
`sha256(b"my_pa.reports.creator.v1\\x00" + kind + b"\\x00" + subject)`: a
pseudonym, comparable for equality only, that never discloses the client id it
was derived from. It is an unkeyed SHA-256, so anyone who can guess the
subject (a principal id or an OAuth client id) can confirm it: it hides the
subject only from observers who cannot enumerate it, and a keyed derivation,
which would rename every creator, is deferred. It is not an `IdKind` (it is
never issued), and its prefix collides with none. Stdlib only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from my_pa.domain.reports.errors import ReportValidationError

__all__ = [
    "CREATOR_DOMAIN_TAG",
    "CREATOR_ID_PATTERN",
    "CREATOR_ID_PREFIX",
    "CreatorKind",
    "ReportCreator",
    "derive_creator",
    "validate_creator_id",
]

#: The derivation's domain-separation tag (frozen: changing it renames every creator).
CREATOR_DOMAIN_TAG: Final = b"my_pa.reports.creator.v1"
CREATOR_ID_PREFIX: Final = "gcrt"
#: The frozen pattern the schema restates as a literal.
CREATOR_ID_PATTERN: Final = r"^gcrt_[0-9a-f]{40}$"

_CREATOR_ID: Final = re.compile(r"\Agcrt_[0-9a-f]{40}\Z")
_DIGEST_HEX_DIGITS: Final = 40


class CreatorKind(StrEnum):
    """How the creator authenticated: on the local transport or as a remote client."""

    LOCAL_PRINCIPAL = "local_principal"
    REMOTE_CLIENT = "remote_client"


def validate_creator_id(value: object, field: str = "created_by") -> str:
    """`value` when it is a creator pseudonym, else `ReportValidationError(field, "pattern")`."""
    if not isinstance(value, str):
        raise ReportValidationError(field, "type")
    if not _CREATOR_ID.fullmatch(value):
        raise ReportValidationError(field, "pattern")
    return value


@dataclass(frozen=True, slots=True)
class ReportCreator:
    """A creator or author: its kind and its pseudonym."""

    kind: CreatorKind
    creator_id: str

    def __post_init__(self) -> None:
        kind: object = self.kind
        if not isinstance(kind, str):
            raise ReportValidationError("creator", "type")
        try:
            object.__setattr__(self, "kind", CreatorKind(kind))
        except ValueError:
            raise ReportValidationError("creator", "kind") from None
        validate_creator_id(self.creator_id, "creator")


def derive_creator(kind: CreatorKind, subject: str) -> ReportCreator:
    """The creator of `subject` authenticated as `kind`: deterministic, kind-separated."""
    creator_kind = CreatorKind(kind)
    # Typed as `object`: a composition fault may hand in anything.
    value: object = subject
    if not isinstance(value, str) or not value:
        raise ReportValidationError("creator", "subject")
    digest = hashlib.sha256(
        CREATOR_DOMAIN_TAG
        + b"\x00"
        + creator_kind.value.encode("utf-8")
        + b"\x00"
        + subject.encode("utf-8")
    ).hexdigest()
    return ReportCreator(
        kind=creator_kind, creator_id=f"{CREATOR_ID_PREFIX}_{digest[:_DIGEST_HEX_DIGITS]}"
    )
