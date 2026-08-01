"""The source registry: configured sources, and how their identities are issued.

A configured source is one operator declaration that a provider-served
collection may be read. What the registry models is deliberately less than what
persistence stores: an opaque `src_…`, which provider serves it, a safe label,
and the classification of what lives there. Where it physically is does not
appear here at all. The provider-native root is persistence's private column, so
no domain value can carry it into a response, a log, or an error
(`docs/specs` section 8.4, `INV-PKL-005`).

Identity is *issued* here, never derived. `domain.common.identifiers` validates
shape only, and says so in its own docstring: an alphanumeric suffix rules out a
raw path or host, but nothing there can tell that `src_taxreturn2025` is
semantic. `issue_identifier` is the issuer that discharges that responsibility,
and it does it the one way a shape check cannot be fooled by — `secrets.token_hex`,
whose output is independent of the thing being named. Deriving a suffix from a
path, a filename, a row id, a natural key, or a hash of any of those would
produce an identifier that validates and still leaks; a hash is not opacity,
because the input space of filenames is small enough to enumerate.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, make_identifier, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "ConfiguredSource",
    "InvalidSourceLabelError",
    "SourceProviderKind",
    "issue_identifier",
    "validate_source_label",
]

#: 16 random bytes render as 32 hex characters, which sits inside the 8-64
#: alphanumeric suffix the validator requires and leaves the whole identifier
#: well under the 72-character ceiling. 128 bits is far past any collision
#: concern for a single-operator corpus, and the cost of a wider suffix is zero,
#: so there is no reason to economise here.
_SUFFIX_BYTES: Final = 16

#: A label is for a human reading a list of sources. It is bounded to printable
#: word characters, spaces, hyphens, and underscores, so a path, a URI, a host,
#: or an address cannot be stored as one: `/`, `\`, `.`, `:`, and `@` are all
#: outside the class. As with identifier suffixes this is a shape check and not
#: a semantic one — "Bob's tax returns" is a legal label — but it removes the
#: mechanical leak, which is the part a check can remove.
_LABEL_PATTERN: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9 _-]{0,63}\Z")


class SourceProviderKind(StrEnum):
    """Which provider implementation serves a configured source.

    One member, because one provider exists. A second arrives with the adapter
    that implements it, not before it: an enum value with no implementation
    behind it is a promise the registry cannot keep.
    """

    FIXTURE = "fixture"


class InvalidSourceLabelError(ValueError):
    """Raised when a source label is missing or is not a safe display name."""


def issue_identifier(kind: IdKind) -> str:
    """Issue a fresh opaque identifier of `kind`.

    Takes no subject argument on purpose. A function that accepted the object
    being named could derive the suffix from it, and every caller would then
    have to be reviewed for whether it did; a function that cannot see the
    subject cannot encode it.
    """
    return make_identifier(kind, secrets.token_hex(_SUFFIX_BYTES))


def validate_source_label(label: str) -> str:
    """Return `label` unchanged, or raise `InvalidSourceLabelError`.

    Names the defect and never echoes the value, following the redaction
    discipline in `bootstrap.settings`: a rejected label is exactly the case
    where the value may be the private string that made it fail.
    """
    if not isinstance(label, str):
        raise InvalidSourceLabelError(f"source label must be a string, got {type(label).__name__}")
    if not _LABEL_PATTERN.fullmatch(label):
        raise InvalidSourceLabelError(
            "source label must be 1-64 characters of letters, digits, spaces, "
            "hyphens, or underscores and must not contain a path, host, or address"
        )
    return label


@dataclass(frozen=True, slots=True)
class ConfiguredSource:
    """One source the operator has configured, as the contract may disclose it.

    There is no locator field, and adding one would be the visible, reviewable
    act it should be. `classification` states what the content is, not what may
    be done with it: `domain.common.classification` is explicit that
    classification alone grants nothing.
    """

    source_id: str
    provider_kind: SourceProviderKind
    label: str
    classification: Classification
    configured_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_source_label(self.label)
        object.__setattr__(self, "configured_at", ensure_utc(self.configured_at))
