"""Value objects of record lineage, Slice S1 (S1 contract sections 3.1, 5.1, 7.1).

`RecordRef` names one endpoint root; `EvidenceAnchor` is the ten-key anchor
object of section 5.1 with `source_version_no` already filled by the server
from the bound version row (a client never supplies it). Both validate their
own shape on construction, so `domain.lineage.canonical` only ever encodes a
well-formed value. Neither persists, mints an identifier or reads a clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage.vocabulary import (
    RECORD_FAMILY_ID_KINDS,
    EvidenceRole,
    EvidenceSourceFamily,
    RecordFamily,
    SourceVersionKind,
)

__all__ = [
    "MAX_EVIDENCE_ANCHORS",
    "MAX_ISSUE_DESCRIPTION_CHARACTERS",
    "MAX_ISSUE_TITLE_CHARACTERS",
    "MAX_LINEAGE_IDEMPOTENCY_KEY_CHARACTERS",
    "MAX_LINEAGE_REASON_CHARACTERS",
    "MAX_NORMALIZED_IDENTITY_CHARACTERS",
    "EvidenceAnchor",
    "InvalidLineageValueError",
    "RecordRef",
]

#: At most this many anchors in one link revision's evidence set (section 4.2).
MAX_EVIDENCE_ANCHORS: Final = 32
#: An Issue title is 1..500 characters after trimming (section 4.2).
MAX_ISSUE_TITLE_CHARACTERS: Final = 500
#: An Issue description is at most 10000 characters (section 4.2).
MAX_ISSUE_DESCRIPTION_CHARACTERS: Final = 10000
#: A link or Project-link reason is 1..2000 characters (section 4.2).
MAX_LINEAGE_REASON_CHARACTERS: Final = 2000
#: A stored `normalized_identity` is 1..1024 characters (section 4.2).
MAX_NORMALIZED_IDENTITY_CHARACTERS: Final = 1024
#: A lineage idempotency key is 1..128 characters (section 4.2).
MAX_LINEAGE_IDEMPOTENCY_KEY_CHARACTERS: Final = 128

_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")

#: The root and version identifier kinds each evidence source family binds.
_SOURCE_KINDS: Final[dict[EvidenceSourceFamily, tuple[IdKind, IdKind | None]]] = {
    EvidenceSourceFamily.MEETING_NOTE_VERSION: (IdKind.MEETING, IdKind.MEETING_NOTE_VERSION),
    EvidenceSourceFamily.CAPTURE_VERSION: (IdKind.CAPTURE, IdKind.CAPTURE_VERSION),
    EvidenceSourceFamily.CAPTURE: (IdKind.CAPTURE, None),
}


class InvalidLineageValueError(ValueError):
    """A lineage value object was constructed with a malformed field."""


@dataclass(frozen=True, slots=True)
class RecordRef:
    """One endpoint root: a family and the record identifier of that family."""

    family: RecordFamily
    record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.family, RecordFamily):
            raise InvalidLineageValueError("a record reference names an S1 record family")
        try:
            validate_identifier(self.record_id, RECORD_FAMILY_ID_KINDS[self.family])
        except ValueError as error:
            raise InvalidLineageValueError(
                "a record reference carries an identifier of its family"
            ) from error


@dataclass(frozen=True, slots=True)
class EvidenceAnchor:
    """The section 5.1 anchor object, keys spelled exactly as the contract does."""

    source_family: EvidenceSourceFamily
    source_root_id: str
    source_version_kind: SourceVersionKind
    source_version_id: str | None
    source_version_no: int | None
    source_sha256: str | None
    passage_start_cp: int | None
    passage_end_cp: int | None
    passage_sha256: str | None
    role: EvidenceRole

    def __post_init__(self) -> None:
        if not isinstance(self.source_family, EvidenceSourceFamily):
            raise InvalidLineageValueError("an anchor names an S1 evidence source family")
        if not isinstance(self.source_version_kind, SourceVersionKind):
            raise InvalidLineageValueError("an anchor names a source version kind")
        if not isinstance(self.role, EvidenceRole):
            raise InvalidLineageValueError("an anchor names an evidence role")
        root_kind, version_kind = _SOURCE_KINDS[self.source_family]
        try:
            validate_identifier(self.source_root_id, root_kind)
        except ValueError as error:
            raise InvalidLineageValueError("an anchor root is of its family") from error
        if self.source_family is EvidenceSourceFamily.CAPTURE:
            self._check_legacy_root()
        else:
            self._check_immutable_version(version_kind)
        self._check_passage()

    def _check_legacy_root(self) -> None:
        if self.source_version_kind is not SourceVersionKind.LEGACY_UNVERSIONED:
            raise InvalidLineageValueError("a capture root anchor is legacy_unversioned")
        if any(
            value is not None
            for value in (
                self.source_version_id,
                self.source_version_no,
                self.source_sha256,
                self.passage_start_cp,
                self.passage_end_cp,
                self.passage_sha256,
            )
        ):
            raise InvalidLineageValueError(
                "a legacy capture root pins no version, digest or passage"
            )
        if self.role not in (EvidenceRole.CORROBORATES, EvidenceRole.CONTRADICTS):
            raise InvalidLineageValueError("a legacy capture root only corroborates or contradicts")

    def _check_immutable_version(self, version_kind: IdKind | None) -> None:
        if self.source_version_kind is not SourceVersionKind.IMMUTABLE_VERSION:
            raise InvalidLineageValueError("a version anchor pins an immutable version")
        if self.source_version_id is None or version_kind is None:
            raise InvalidLineageValueError("a version anchor names its version")
        try:
            validate_identifier(self.source_version_id, version_kind)
        except ValueError as error:
            raise InvalidLineageValueError("an anchor version is of its family") from error
        number = self.source_version_no
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise InvalidLineageValueError("a version anchor carries its version number")
        if not isinstance(self.source_sha256, str) or not _SHA256_HEX.match(self.source_sha256):
            raise InvalidLineageValueError("a version anchor carries its source digest")

    def _check_passage(self) -> None:
        triple = (self.passage_start_cp, self.passage_end_cp, self.passage_sha256)
        if all(value is None for value in triple):
            return
        start, end, digest = triple
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or not isinstance(digest, str)
        ):
            raise InvalidLineageValueError("a passage is whole: start, end and digest")
        if not 0 <= start < end:
            raise InvalidLineageValueError("a passage starts before it ends, at zero or later")
        if not _SHA256_HEX.match(digest):
            raise InvalidLineageValueError("a passage digest is lowercase SHA-256 hex")
