"""Evidence anchor input and admission, record lineage S1 (S1 contract 3.1, 3.2, 5, 7.1).

This module holds the part of S1 endpoint validation the Issue Project-link
writes need: one `EvidenceAnchorInput` (`issues.project_links.add`'s optional
`evidence_anchor`), parsed from a caller document, then admitted against its
locked source. The record-link endpoint checks of section 3.2 (Tasks,
Commitments, Constraints, Meetings, Issue endpoints) belong to the association
and membership writes and are not here.

**Parse** (`parse_evidence_anchor`): exactly the section 7.1 keys; `family` is
`meeting_note_version`, `capture_version` or `capture`; `immutable_version`
requires `version_id` and `source_sha256`; `legacy_unversioned` is the `capture`
family only and pins no version, digest or passage; a passage is whole. A
`version_no` is never accepted: the server fills it.

**Admit** (`admit_evidence_anchor`), in the section 3.2 check order: (1) the
identifier prefixes (already enforced by the parse); (2) Principal-scoped
existence under the right parent, taken `FOR SHARE` -- absent, foreign and
wrong-parent are one `not_found`; (3) only then the Capture root's lifecycle
(`denied` / `capture_withdrawn` when archived), the version's classification
(`synthetic_test` or `private_local`, else `invalid_request`), the legacy root's
point-in-time restricted-version refusal (F21/F24), the stored source digest and
the passage digest. The anchor is then reused or inserted by its canonical
identity; its `source_version_no` is the bound row's `version_number`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.application.errors import (
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import IssueRepository, LineageSourceVersion
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.lineage.canonical import passage_sha256
from my_pa.domain.lineage.model import EvidenceAnchor, InvalidLineageValueError
from my_pa.domain.lineage.vocabulary import (
    EvidenceRole,
    EvidenceSourceFamily,
    SourceVersionKind,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "EVIDENCE_ANCHOR_INPUT_KEYS",
    "EvidenceAnchorInput",
    "LockedEvidenceSource",
    "admit_evidence_anchor",
    "lock_evidence_source",
    "parse_evidence_anchor",
]

#: The admitted keys of one `EvidenceAnchorInput` document (section 7.1).
EVIDENCE_ANCHOR_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "family",
        "root_id",
        "version_kind",
        "version_id",
        "source_sha256",
        "passage_start_cp",
        "passage_end_cp",
        "passage_sha256",
        "role",
    }
)

#: The Capture classifications an S1 anchor may bind (restricted is S3).
_ADMITTED_CLASSIFICATIONS: Final = frozenset(
    {Classification.SYNTHETIC_TEST.value, Classification.PRIVATE_LOCAL.value}
)

_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")

#: The root and version identifier kinds each anchor family names.
_KINDS: Final[dict[EvidenceSourceFamily, tuple[IdKind, IdKind | None]]] = {
    EvidenceSourceFamily.MEETING_NOTE_VERSION: (IdKind.MEETING, IdKind.MEETING_NOTE_VERSION),
    EvidenceSourceFamily.CAPTURE_VERSION: (IdKind.CAPTURE, IdKind.CAPTURE_VERSION),
    EvidenceSourceFamily.CAPTURE: (IdKind.CAPTURE, None),
}


@dataclass(frozen=True, slots=True)
class EvidenceAnchorInput:
    """One caller-supplied anchor, shape-checked; nothing here is server-derived."""

    family: EvidenceSourceFamily
    root_id: str
    version_kind: SourceVersionKind
    version_id: str | None
    source_sha256: str | None
    passage_start_cp: int | None
    passage_end_cp: int | None
    passage_sha256: str | None
    role: EvidenceRole

    def digest_document(self) -> dict[str, object]:
        """The anchor as the request digest holds it: every key, `null` when absent."""
        return {
            "family": self.family.value,
            "root_id": self.root_id,
            "version_kind": self.version_kind.value,
            "version_id": self.version_id,
            "source_sha256": self.source_sha256,
            "passage_start_cp": self.passage_start_cp,
            "passage_end_cp": self.passage_end_cp,
            "passage_sha256": self.passage_sha256,
            "role": self.role.value,
        }


def _member[MemberT](value: object, vocabulary: type[MemberT], detail: SafeDetail) -> MemberT:
    if isinstance(value, str):
        try:
            return vocabulary(value)  # type: ignore[call-arg]
        except ValueError:
            pass
    raise InvalidRequestError(detail)


def _optional_text(value: object, detail: SafeDetail) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise InvalidRequestError(detail)


def _optional_offset(value: object, minimum: int, detail: SafeDetail) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InvalidRequestError(detail)
    return value


def _identifier(value: object, kind: IdKind, detail: SafeDetail) -> str:
    refused = not isinstance(value, str)
    if not refused:
        try:
            validate_identifier(value, kind)  # type: ignore[arg-type]
        except InvalidIdentifierError:
            refused = True
    if refused:
        raise InvalidRequestError(detail)
    return value  # type: ignore[return-value]


def parse_evidence_anchor(document: object, detail: SafeDetail) -> EvidenceAnchorInput:
    """One `EvidenceAnchorInput` from a caller document, or `invalid_request` / `detail`."""
    if not isinstance(document, Mapping) or not set(document) <= EVIDENCE_ANCHOR_INPUT_KEYS:
        raise InvalidRequestError(detail)
    family = _member(document.get("family"), EvidenceSourceFamily, detail)
    version_kind = _member(document.get("version_kind"), SourceVersionKind, detail)
    role = _member(document.get("role"), EvidenceRole, detail)
    root_kind, version_id_kind = _KINDS[family]
    root_id = _identifier(document.get("root_id"), root_kind, detail)
    version_id = _optional_text(document.get("version_id"), detail)
    if version_id is not None:
        if version_id_kind is None:
            raise InvalidRequestError(detail)
        _identifier(version_id, version_id_kind, detail)
    source_digest = _optional_text(document.get("source_sha256"), detail)
    passage_digest = _optional_text(document.get("passage_sha256"), detail)
    for digest in (source_digest, passage_digest):
        if digest is not None and not _SHA256_HEX.match(digest):
            raise InvalidRequestError(detail)
    start = _optional_offset(document.get("passage_start_cp"), 0, detail)
    end = _optional_offset(document.get("passage_end_cp"), 1, detail)
    anchor = EvidenceAnchorInput(
        family=family,
        root_id=root_id,
        version_kind=version_kind,
        version_id=version_id,
        source_sha256=source_digest,
        passage_start_cp=start,
        passage_end_cp=end,
        passage_sha256=passage_digest,
        role=role,
    )
    # The domain value object holds every remaining shape rule (version kind per
    # family, legacy roots pin nothing and only corroborate or contradict, a
    # passage is whole and ordered). A placeholder version number stands in for
    # the server-derived one, which a shape check cannot know.
    _shape_checked(anchor, source_version_no=None if version_id is None else 1, detail=detail)
    return anchor


def _shape_checked(
    anchor: EvidenceAnchorInput, *, source_version_no: int | None, detail: SafeDetail
) -> EvidenceAnchor:
    refused = False
    try:
        return EvidenceAnchor(
            source_family=anchor.family,
            source_root_id=anchor.root_id,
            source_version_kind=anchor.version_kind,
            source_version_id=anchor.version_id,
            source_version_no=source_version_no,
            source_sha256=anchor.source_sha256,
            passage_start_cp=anchor.passage_start_cp,
            passage_end_cp=anchor.passage_end_cp,
            passage_sha256=anchor.passage_sha256,
            role=anchor.role,
        )
    except InvalidLineageValueError:
        refused = True
    if refused:
        raise InvalidRequestError(detail)
    raise AssertionError("unreachable")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class LockedEvidenceSource:
    """One anchor's source after section 3.2 step 2: locked, owned, under its parent.

    `version` is `None` for a legacy Capture root, which binds no version.
    """

    anchor: EvidenceAnchorInput
    version: LineageSourceVersion | None


def lock_evidence_source(
    issues: IssueRepository, principal_id: str, anchor: EvidenceAnchorInput, detail: SafeDetail
) -> LockedEvidenceSource:
    """Section 3.2 step 2 for one anchor: `FOR SHARE`, or one `not_found`.

    A note anchor shares its note version under its Meeting; a Capture anchor
    shares its root (`share_capture_root`, which an archive waits on) and then,
    for a version anchor, the version under that root.
    """
    if anchor.family is EvidenceSourceFamily.MEETING_NOTE_VERSION:
        if anchor.version_id is None:
            raise InvalidRequestError(detail)
        note = issues.share_note_version(principal_id, anchor.root_id, anchor.version_id)
        if note is None:
            raise NotFoundError(detail)
        return LockedEvidenceSource(anchor=anchor, version=note)
    if not issues.share_capture_root(principal_id, anchor.root_id):
        raise NotFoundError(detail)
    version: LineageSourceVersion | None = None
    if anchor.family is EvidenceSourceFamily.CAPTURE_VERSION:
        if anchor.version_id is None:
            raise InvalidRequestError(detail)
        version = issues.share_capture_version(principal_id, anchor.root_id, anchor.version_id)
        if version is None:
            raise NotFoundError(detail)
    return LockedEvidenceSource(anchor=anchor, version=version)


def admit_evidence_anchor(
    issues: IssueRepository,
    principal_id: str,
    locked: LockedEvidenceSource,
    *,
    recorded_at: datetime,
    detail: SafeDetail,
) -> str:
    """Section 3.2 step 3 for one locked source, then reuse-or-insert the anchor."""
    anchor = locked.anchor
    source = locked.version
    if anchor.family is not EvidenceSourceFamily.MEETING_NOTE_VERSION:
        if issues.capture_root_is_archived(principal_id, anchor.root_id):
            raise DeniedError(SafeDetail.CAPTURE_WITHDRAWN)
        if source is None:
            # A legacy root (F21/F24): refused, point in time, when any committed
            # version of it is restricted.
            if issues.capture_root_has_restricted_version(principal_id, anchor.root_id):
                raise InvalidRequestError(detail)
        elif source.classification not in _ADMITTED_CLASSIFICATIONS:
            raise InvalidRequestError(detail)
    if source is not None:
        if anchor.source_sha256 != source.content_sha256:
            raise InvalidRequestError(detail)
        start, end = anchor.passage_start_cp, anchor.passage_end_cp
        if start is not None or end is not None:
            refused = start is None or end is None
            expected = ""
            if start is not None and end is not None:
                try:
                    expected = passage_sha256(source.body, start, end)
                except InvalidLineageValueError:
                    refused = True
            if refused or expected != anchor.passage_sha256:
                raise InvalidRequestError(detail)
    bound = _shape_checked(
        anchor,
        source_version_no=None if source is None else source.version_number,
        detail=detail,
    )
    return issues.admit_anchor(
        principal_id,
        bound,
        anchor_id=issue_identifier(IdKind.LINEAGE_EVIDENCE_ANCHOR),
        recorded_at=recorded_at,
    )
