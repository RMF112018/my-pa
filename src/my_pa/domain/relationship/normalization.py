"""Deterministic normalization for entity resolution.

Normalization decides which two strings are "the same", and every rule here is
therefore a rule about which two *people* the system may treat as one. The
specification asks for "exact and normalized names" (section 15.1) and a
"normalize observation" pipeline stage (section 27.1) and defines neither, so
each rule below is a decision this work package makes rather than one it
inherits. They are collected in one module so a reviewer can read the whole
matching policy in one place instead of inferring it from call sites.

**The bias is conservative in one direction, deliberately.** Section 15.2 says
ambiguous mentions "remain unresolved rather than forced into the nearest
person", and `RI-RISK-001` names a false merge as contaminating profile,
timeline, commitments and briefings. A normalization that is too *narrow*
produces a duplicate the review plane can merge later; one that is too *wide*
produces a false join that has already contaminated everything downstream by
the time anyone notices. So where a rule could go either way, it goes narrow.

Three consequences of that, each of which looks like a missing feature until the
failure it prevents is named:

* **Email local-parts are not rewritten.** Dots and `+tags` are folded by some
  providers and significant at others. `a.b@example.com` and `ab@example.com`
  are one mailbox at Gmail and two anywhere else, so folding them is a false
  join everywhere except the one provider that inspired the rule. The domain is
  lowercased because DNS is case-insensitive by specification; the local-part is
  lowercased because every mail system in this product's reach treats it so, and
  that is a narrower claim than rewriting it.
* **Opaque vendor and source identifiers are compared exactly.** An
  `entra_object_id` is a UUID and is case-folded; a `vendor_system_id` or a
  `source_participant_id` is an opaque string from a system whose case rules are
  unknown, and folding it could collide two distinct records.
* **Punctuation in a name becomes a separator, not nothing.** `O'Brien`
  normalizes to `o brien` rather than `obrien`, so it does not match a different
  person named `Obrien`. It also means `O'Brien` and `OBrien` do not match each
  other -- a duplicate rather than a false join, which is the trade this module
  is built to make.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

__all__ = [
    "CASE_FOLDED_NAMESPACES",
    "ExternalIdentifierNamespace",
    "NormalizationError",
    "is_normalized_identifier",
    "is_normalized_name",
    "normalize_identifier",
    "normalize_name",
]


class ExternalIdentifierNamespace(StrEnum):
    """The external namespaces where an entity may hold an identity.

    Declared here rather than beside `Entity`, because the namespace and the
    rule for normalizing within it are one fact: the enum's whole meaning is
    "which comparison applies". Keeping them apart forced the dependency the
    wrong way round -- `entity` could not check that a stored value was
    normalized without importing the module that imports it. Re-exported from
    `domain.relationship.entity`, so every existing import still resolves.

    Closed as of this revision; widening is a visible schema change.
    """

    EMAIL = "email"
    ENTRA_OBJECT_ID = "entra_object_id"
    TEAMS_USER_ID = "teams_user_id"
    OUTLOOK_CONTACT_ID = "outlook_contact_id"
    APPLE_CONTACT_ID = "apple_contact_id"
    SOURCE_PARTICIPANT_ID = "source_participant_id"
    VENDOR_SYSTEM_ID = "vendor_system_id"


class NormalizationError(ValueError):
    """A value could not be normalized into something matchable.

    Raised rather than returned as an empty string, because an empty normalized
    value would match nothing *or* everything depending on the query it reached,
    and neither is an answer a caller should get by accident.
    """


#: The namespaces whose values are case-insensitive by their own specification,
#: and may therefore be folded without inventing an equivalence.
#:
#: `EMAIL` is folded because mail systems in this product's reach treat mailbox
#: names case-insensitively. `ENTRA_OBJECT_ID` is a UUID, and RFC 9562 states
#: that the hexadecimal is case-insensitive on input.
#:
#: Everything else is absent on purpose: `TEAMS_USER_ID`, `OUTLOOK_CONTACT_ID`,
#: `APPLE_CONTACT_ID`, `SOURCE_PARTICIPANT_ID` and `VENDOR_SYSTEM_ID` are opaque
#: strings issued by systems whose case rules this product does not know, and
#: folding an identifier whose issuer treats case as significant merges two
#: records that the issuer keeps apart.
CASE_FOLDED_NAMESPACES: frozenset[ExternalIdentifierNamespace] = frozenset(
    {
        ExternalIdentifierNamespace.EMAIL,
        ExternalIdentifierNamespace.ENTRA_OBJECT_ID,
    }
)

#: Anything that is not a letter, a digit, or whitespace. Replaced with a space
#: rather than removed, for the reason the module docstring gives.
_PUNCTUATION = re.compile(r"[^\w\s]|_", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_name(value: str) -> str:
    """`value` as the form two names are compared in.

    Unicode-normalized to NFKD and stripped of combining marks, so `José` and
    `Jose` match -- a diacritic is a rendering of the same name rather than a
    different person, and source systems disagree about carrying it. Then
    case-folded, punctuation-separated, and whitespace-collapsed.

    `casefold` rather than `lower`, because `lower` leaves `ß` alone while
    `casefold` maps it to `ss`, and a German surname should match itself across
    two source systems that spell it differently.

    Raises `NormalizationError` when nothing matchable is left.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    separated = _PUNCTUATION.sub(" ", without_marks)
    collapsed = _WHITESPACE.sub(" ", separated).strip()
    folded = collapsed.casefold()
    if not folded:
        raise NormalizationError("a name normalizes to nothing matchable")
    return folded


def _normalize_email(value: str) -> str:
    """An address as it is compared: the domain lowercased, the local-part folded.

    The local-part is **not** rewritten -- see the module docstring. The address
    must contain exactly one `@` with something on each side; anything else is
    refused rather than stored as a value that would never match.
    """
    stripped = value.strip()
    local, separator, domain = stripped.rpartition("@")
    if not separator or not local or not domain:
        raise NormalizationError("an email identifier has a local part and a domain")
    if "@" in local:
        raise NormalizationError("an email identifier has exactly one at sign")
    if any(character.isspace() for character in stripped):
        raise NormalizationError("an email identifier carries no whitespace")
    return f"{local.casefold()}@{domain.casefold()}"


def normalize_identifier(namespace: ExternalIdentifierNamespace, value: str) -> str:
    """`value` as the form two identifiers in `namespace` are compared in.

    Dispatches on the namespace rather than applying one rule to every
    identifier, because "the same identifier" means different things in
    different namespaces and a single rule would have to be either the widest
    (which false-joins) or the narrowest (which never matches an email that
    differs only in case).
    """
    if not isinstance(namespace, ExternalIdentifierNamespace):
        raise NormalizationError("an identifier is normalized within a closed namespace")
    if namespace is ExternalIdentifierNamespace.EMAIL:
        return _normalize_email(value)
    stripped = value.strip()
    if not stripped:
        raise NormalizationError("an identifier normalizes to nothing matchable")
    if namespace in CASE_FOLDED_NAMESPACES:
        return stripped.casefold()
    return stripped


def is_normalized_name(value: str) -> bool:
    """Whether `value` is already the form `normalize_name` produces.

    The write-side half of this module. Every rule above is a rule about which
    two *people* the system may treat as one, and until a writer was obliged to
    honour them they were a query-side convention: a stored name that had been
    normalized differently -- or not at all -- silently changed who a reference
    resolved to, including turning a refusal into a match on a *neighbouring*
    row. The records enforce it now, so the rules bind both sides.
    """
    try:
        return normalize_name(value) == value
    except NormalizationError:
        return False


def is_normalized_identifier(namespace: ExternalIdentifierNamespace, value: str) -> bool:
    """Whether `value` is already the form `normalize_identifier` produces."""
    try:
        return normalize_identifier(namespace, value) == value
    except NormalizationError:
        return False
