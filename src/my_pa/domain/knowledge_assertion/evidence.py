"""Knowledge evidence identity and observed classification (KLP-WP-01).

One canonical evidence row exists per source identity (plan section 5.1):
external evidence is identified by (source profile, external object, external
version or "", content hash), capture evidence by (capture, content hash) and
Relationship Memory evidence by (memory, content hash). `EvidenceIdentity`
states those three shapes, and `canonical_sort_key` is the one order in which
new identities are upserted and in which the request digest lists evidence.

`observed_external_classification` is the server's class for external evidence
on submit. It is the rank-max of the source-profile floor and the **sibling
max**, i.e. the stored class of every row of the same Principal with the same
origin_system and external_object_id across all profiles and versions
(KLP-R6V-005, corrected wording of KLP-R6V-203). A caller never declares a
class, and a re-observation can only raise it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from my_pa.domain.common.classification import Classification, classification_max
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceIdentityKind

__all__ = [
    "MAX_EXCERPT_CHARACTERS",
    "MAX_EXTERNAL_ID_CHARACTERS",
    "EvidenceIdentity",
    "InvalidKnowledgeEvidenceError",
    "observed_external_classification",
    "profile_floor",
]

MAX_EXTERNAL_ID_CHARACTERS: Final = 512
MAX_EXCERPT_CHARACTERS: Final = 2048
_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")


class InvalidKnowledgeEvidenceError(ValueError):
    """Raised when an evidence identity has an illegal shape. Names fields, never values."""


def _external_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_EXTERNAL_ID_CHARACTERS
        or _CONTROL.search(value)
    ):
        raise InvalidKnowledgeEvidenceError(
            f"{field} must be 1..512 characters with no control characters"
        )
    return value


def _opaque(value: object, kind: IdKind, field: str) -> str:
    try:
        return validate_identifier(value, kind)  # type: ignore[arg-type]
    except InvalidIdentifierError as exc:
        raise InvalidKnowledgeEvidenceError(f"{field} is not a {kind.value}_ identifier") from exc


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    """Exactly one identity shape (CHECK `knowledge_evidence_ref_has_one_identity_shape`)."""

    identity_kind: KnowledgeEvidenceIdentityKind
    content_hash: str
    source_profile_id: str | None = None
    external_object_id: str | None = None
    external_version_id: str | None = None
    capture_id: str | None = None
    relationship_memory_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity_kind, KnowledgeEvidenceIdentityKind):
            raise InvalidKnowledgeEvidenceError("identity_kind must be a closed token")
        content_hash: object = self.content_hash
        if not isinstance(content_hash, str) or not _SHA256_HEX.fullmatch(content_hash):
            raise InvalidKnowledgeEvidenceError("content_hash must be lowercase SHA-256 hex")
        external = (self.source_profile_id, self.external_object_id, self.external_version_id)
        kind = self.identity_kind
        if kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT:
            if self.capture_id is not None or self.relationship_memory_id is not None:
                raise InvalidKnowledgeEvidenceError("external evidence names no capture or memory")
            _opaque(
                self.source_profile_id,
                IdKind.KNOWLEDGE_DISCOVERY_SOURCE_PROFILE,
                "source_profile_id",
            )
            _external_id(self.external_object_id, "external_object_id")
            if self.external_version_id is not None:
                _external_id(self.external_version_id, "external_version_id")
        elif kind is KnowledgeEvidenceIdentityKind.CAPTURE:
            if (
                any(part is not None for part in external)
                or self.relationship_memory_id is not None
            ):
                raise InvalidKnowledgeEvidenceError("capture evidence names only a capture")
            _opaque(self.capture_id, IdKind.CAPTURE, "capture_id")
        else:
            if any(part is not None for part in external) or self.capture_id is not None:
                raise InvalidKnowledgeEvidenceError("memory evidence names only a memory")
            _opaque(
                self.relationship_memory_id, IdKind.RELATIONSHIP_MEMORY, "relationship_memory_id"
            )

    @property
    def identity(self) -> tuple[str, ...]:
        """The identity tuple of the request-digest object (plan section 6.2)."""
        if self.identity_kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT:
            return (
                str(self.source_profile_id),
                str(self.external_object_id),
                self.external_version_id or "",
            )
        if self.identity_kind is KnowledgeEvidenceIdentityKind.CAPTURE:
            return (str(self.capture_id),)
        return (str(self.relationship_memory_id),)

    def canonical_sort_key(self) -> tuple[str, tuple[str, ...], str]:
        """(identity_kind, identity tuple, content_hash): the upsert and digest order."""
        return (self.identity_kind.value, self.identity, self.content_hash)


def profile_floor(*, profile_is_synthetic: bool) -> Classification:
    """`synthetic_test` for a synthetic source profile, otherwise `private_local`."""
    return Classification.SYNTHETIC_TEST if profile_is_synthetic else Classification.PRIVATE_LOCAL


def observed_external_classification(
    *, profile_is_synthetic: bool, sibling_classifications: Iterable[Classification]
) -> Classification:
    """rank-max(profile floor, sibling max) for external evidence on submit.

    `sibling_classifications` are the stored classes of every evidence row of the
    same Principal with the same origin_system and external_object_id, under any
    source profile or version. A changed version or an overlapping profile can
    therefore never launder a restriction.
    """
    return classification_max(
        profile_floor(profile_is_synthetic=profile_is_synthetic), *sibling_classifications
    )
