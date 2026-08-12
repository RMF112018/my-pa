"""Opaque, server-issued identifiers.

Each identifier is a short type prefix joined to an opaque suffix by a single
underscore. `INV-PKL-005` requires that public identifiers not encode filesystem
paths, provider names, hosts, accounts, or database keys.

Validation here enforces *shape* only: the alphanumeric suffix rule rules out
path separators, dots, colons, and `@`, so a raw path or host cannot appear
verbatim. It cannot tell that `src_taxreturn2025` is semantic. Keeping suffixes
non-semantic is the issuer's responsibility, not something this module can check.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

__all__ = [
    "IdKind",
    "InvalidIdentifierError",
    "make_identifier",
    "parse_identifier",
    "validate_identifier",
]

_SUFFIX_PATTERN: Final = re.compile(r"\A[A-Za-z0-9]{8,64}\Z")
_MAX_LENGTH: Final = 72


class IdKind(StrEnum):
    """Identifier types defined by the v1 contract."""

    SOURCE = "src"
    SOURCE_OBJECT = "obj"
    VERSION = "ver"
    ENROLLMENT = "enr"
    #: The capture plane. `CAPTURE_VERSION` is deliberately not `VERSION`, which
    #: already denotes an observed *source object* version: one prefix for two
    #: unrelated things would make an audit row or a stored reference ambiguous
    #: about which plane it belongs to, and no later check could recover the
    #: distinction.
    CAPTURE = "cap"
    CAPTURE_VERSION = "capver"
    RECEIPT = "rcpt"
    SUBMISSION = "sub"
    #: A registered remote capture client (WP-10). Its own prefix rather than a
    #: reuse of `PRINCIPAL`, because a client is a credential bearer bound to a
    #: Principal and not a Principal: one prefix for both would make a stored
    #: reference ambiguous about which of the two it names, and the binding is
    #: exactly the distinction that must stay legible.
    CAPTURE_CLIENT = "cclt"
    #: The capture *processing* plane: what the pipeline derived from a stored
    #: version. Each is its own prefix rather than a shared `derived_` one,
    #: because an audit row or a stored reference has to say which record it
    #: names, and a single prefix would make a proposal and the span it cites
    #: indistinguishable to a reader of either.
    PROCESSING_TEXT = "ptext"
    STAGE_RESULT = "stage"
    SPAN = "span"
    PROPOSAL = "prop"
    CAPTURE_CLASSIFICATION = "ccls"
    CAPTURE_ENTITY_MENTION = "men"
    #: The capture *review and promotion* plane: what a reviewer decided and
    #: what the product now holds as canonical. Each is its own prefix, on the
    #: same argument the processing plane makes — a stored reference has to say
    #: which record it names, and `capture_proposals.accepted_record_id` in
    #: particular carries no foreign key, so its prefix is the only thing in the
    #: value that says what it points at.
    REVIEW_CASE = "rvw"
    REVIEW_DECISION = "rdec"
    ASSERTION = "asrt"
    CONTEXT_LINK = "clink"
    CONVERSATION = "conv"
    PERSON = "per"
    ORGANIZATION = "org"
    IDENTITY_OBSERVATION = "iobs"
    ALIAS = "alias"
    AFFILIATION = "aff"
    UNRESOLVED_MENTION = "umen"
    DUPLICATE_SET = "dups"
    IDENTITY_RESOLUTION = "ires"
    COVERAGE_SNAPSHOT = "cov"
    TIMELINE_ITEM = "tli"
    CONVERSATION_PARTICIPANT = "cpart"
    SOURCE_EVIDENCE = "sevd"
    SOURCE_OBSERVATION = "sobs"
    SOURCE_MEMBERSHIP = "smem"
    NATIVE_BRIDGE = "nbrg"
    NATIVE_ACCOUNT = "nacct"
    NATIVE_BUCKET = "nbkt"
    NATIVE_DISCOVERY = "ndisc"
    NATIVE_CONFIGURATION = "ncfg"
    NATIVE_RUN = "nrun"
    NATIVE_BUCKET_RUN = "nbrun"
    NATIVE_JOB = "njob"
    NATIVE_CHECKPOINT = "ncp"
    NATIVE_SIMULATION = "nsim"
    NATIVE_SIMULATION_RECEIPT = "nsimr"
    NATIVE_LIVE_GATE = "nlg"
    NATIVE_AUTHORITY = "nauth"
    OPERATION = "op"
    KNOWLEDGE = "kn"
    AUDIT = "audit"
    PRINCIPAL = "prn"
    CORRELATION = "corr"
    #: The R5 relationship / project *continuity* plane (WP-06). Each surface is
    #: its own prefix on the same argument the capture planes make — a stored
    #: reference or an audit row has to say which record it names, and a shared
    #: prefix would make a Situation and the Project that groups it, or a Trace
    #: and the relationship event it reconstructed, indistinguishable to a reader
    #: of either. `PROJECT_SITUATION` names the link row itself so that a
    #: reference to the binding is not confused with a reference to either end.
    SITUATION = "sit"
    FRAME = "frm"
    TRACE = "trc"
    PROJECT = "prj"
    PROJECT_SITUATION = "psit"
    RELATIONSHIP_EVENT = "revt"
    PULSE = "puls"
    #: The continuity objects WP-11 adds, and the one append-only record that
    #: carries their lifecycle. `CONTINUITY_DECISION` is deliberately not
    #: `REVIEW_DECISION`: `rdec` names a reviewer's disposition of one proposal
    #: and `cdec` names a decision the Principal holds and has to take, and a
    #: shared prefix would make a stored reference ambiguous about which of the
    #: two it points at — the same argument `CAPTURE_VERSION` makes against
    #: reusing `VERSION`. `LIFECYCLE_EVENT` is its own prefix rather than a reuse
    #: of `RELATIONSHIP_EVENT` for the same reason.
    COMMITMENT = "cmt"
    CONTINUITY_DECISION = "cdec"
    TASK = "tsk"
    LIFECYCLE_EVENT = "lce"
    #: The managed-document plane (WP-27): the one plane whose records name bytes
    #: this product wrote. Five prefixes rather than a reuse of the capture
    #: plane's four, on the argument `CAPTURE_VERSION` makes against reusing
    #: `VERSION`: a stored reference, a receipt and an audit row have to say which
    #: plane they belong to, and `rcpt`/`sub` already name a capture admission —
    #: one prefix for both would make a receipt ambiguous about whether the thing
    #: it acknowledges is a row of text or a file on disk. `MANAGED_LIFECYCLE` is
    #: its own prefix rather than a reuse of `LIFECYCLE_EVENT` for the same
    #: reason: that one names a continuity object's transition.
    #:
    #: A version suffix is also what the byte store derives a location from, so
    #: the shape rule these carry — 8-64 alphanumeric characters, no separator,
    #: no dot — is load-bearing rather than cosmetic.
    MANAGED_DOCUMENT = "mdoc"
    MANAGED_DOCUMENT_VERSION = "mdver"
    MANAGED_RECEIPT = "mdrcpt"
    MANAGED_SUBMISSION = "mdsub"
    MANAGED_LIFECYCLE = "mdlce"


class InvalidIdentifierError(ValueError):
    """Raised when a value is not a well-formed opaque identifier."""


def make_identifier(kind: IdKind, suffix: str) -> str:
    """Build an identifier of `kind` from an already-opaque `suffix`.

    The suffix must be generated by the caller from a non-semantic source. This
    function validates shape only; it cannot detect that a suffix leaks meaning.
    """
    candidate = f"{kind.value}_{suffix}"
    validate_identifier(candidate, kind)
    return candidate


def parse_identifier(value: str) -> tuple[IdKind, str]:
    """Return the kind and suffix of `value`, or raise `InvalidIdentifierError`."""
    validate_identifier(value)
    prefix, _, suffix = value.partition("_")
    return IdKind(prefix), suffix


def validate_identifier(value: str, expected: IdKind | None = None) -> str:
    """Validate `value` as an opaque identifier and return it unchanged.

    Fails closed: anything not matching the documented shape is rejected rather
    than normalised or guessed.
    """
    if not isinstance(value, str):
        # Domain models are plain dataclasses with no runtime type enforcement,
        # so a non-string reaching here must fail as a domain error rather than
        # as an incidental TypeError from len() or partition().
        raise InvalidIdentifierError(f"identifier must be a string, got {type(value).__name__}")
    if len(value) > _MAX_LENGTH:
        raise InvalidIdentifierError(f"identifier exceeds {_MAX_LENGTH} characters")
    prefix, separator, suffix = value.partition("_")
    if not separator:
        raise InvalidIdentifierError("identifier must contain a type prefix and suffix")
    try:
        kind = IdKind(prefix)
    except ValueError as exc:
        raise InvalidIdentifierError(f"unknown identifier prefix: {prefix!r}") from exc
    if not _SUFFIX_PATTERN.fullmatch(suffix):
        raise InvalidIdentifierError("identifier suffix must be 8-64 alphanumeric characters")
    if expected is not None and kind is not expected:
        raise InvalidIdentifierError(f"expected {expected.value!r} identifier, got {prefix!r}")
    return value
