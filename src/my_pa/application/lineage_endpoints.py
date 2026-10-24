"""Endpoint and evidence validation, record lineage S1 (S1 contract 3.1, 3.2, 5, 6.2, 7.1).

Every S1 write that names a record goes through this module: the Issue
Project-link writes (one optional `EvidenceAnchorInput`) and the five link
writes (`issues.memberships.*`, `records.associations.*`: endpoints, an
optional Issue context and an evidence set).

**Family adapters and the lock order** (`lock_lineage_sources`): every
endpoint, Issue, Issue context and evidence source is turned into lock
targets ordered by `(family token, identifier)` and taken `FOR SHARE` in that
order (section 6.2 step 3) -- a Situation, Meeting, note version, Task,
Commitment, Constraint or Capture version row in its native table, an Issue
through `IssueRepository.lock_issue`, a Capture root through
`share_capture_root` (which an archive waits on) and a Capture version under
its root. Each target is checked for Principal-scoped existence under its
parent as it is locked, so the first absent, foreign or wrong-parent one
answers `not_found` with its own subject and nothing is written.

**Linkability** (`require_linkable`) is section 3.2 step 3, only after every
existence check: a context Situation and an archived Task are
`invalid_request` / `endpoint`; a Capture version whose root is archived is
`denied` / `capture_withdrawn`, and one that is neither `synthetic_test` nor
`private_local` is `invalid_request` / `endpoint`.

**The relation matrix and its evidence rules** (`relation_kind`,
`require_relation_evidence`) are section 3.1, `invalid_request` /
`relation_type` and `invalid_request` / `evidence_anchors`.

**The closed-Issue rule** (`require_open_issues`, S2 contract section 3.2): an
Issue in state `closed` named as an endpoint, a membership owner or a
`context_issue_id` of a lineage write is `conflict` / `state`, checked after
every existence check (so a foreign closed Issue is `not_found`).

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal

from my_pa.application.errors import (
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import (
    IssueRecord,
    IssueRepository,
    LineageEndpoint,
    LineageSourceVersion,
    RecordLineageRepository,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.lineage.canonical import (
    DuplicateAnchorIdentityError,
    canonical_evidence,
    passage_sha256,
)
from my_pa.domain.lineage.model import (
    MAX_EVIDENCE_ANCHORS,
    EvidenceAnchor,
    InvalidLineageValueError,
    RecordRef,
)
from my_pa.domain.lineage.vocabulary import (
    RELATION_MATRIX,
    EvidenceRole,
    EvidenceSourceFamily,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SituationKind,
    SourceVersionKind,
)
from my_pa.domain.situation.situation import SituationState
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "EVIDENCE_ANCHOR_INPUT_KEYS",
    "RECORD_REF_KEYS",
    "EvidenceAnchorInput",
    "LockedEvidenceSource",
    "LockedLineageSources",
    "admit_evidence_anchor",
    "admit_evidence_set",
    "anchor_input_of",
    "anchor_inputs_document",
    "bind_evidence_anchor",
    "insert_evidence_anchor",
    "lock_evidence_source",
    "lock_lineage_sources",
    "parse_evidence_anchor",
    "parse_evidence_anchors",
    "parse_record_ref",
    "relation_kind",
    "require_linkable",
    "require_open_issues",
    "require_relation_evidence",
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


def anchor_input_of(anchor: EvidenceAnchor) -> EvidenceAnchorInput:
    """A stored anchor as an input, so its source can be locked in section 6.2 order.

    S2 `issues.close` shares the source of every `resolution` anchor in every
    mandatory member's head revision (R2-F06); those anchors are already bound,
    so only their source identity is needed here.
    """
    return EvidenceAnchorInput(
        family=anchor.source_family,
        root_id=anchor.source_root_id,
        version_kind=anchor.source_version_kind,
        version_id=anchor.source_version_id,
        source_sha256=anchor.source_sha256,
        passage_start_cp=anchor.passage_start_cp,
        passage_end_cp=anchor.passage_end_cp,
        passage_sha256=anchor.passage_sha256,
        role=anchor.role,
    )


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


def bind_evidence_anchor(
    issues: IssueRepository,
    principal_id: str,
    locked: LockedEvidenceSource,
    *,
    detail: SafeDetail,
) -> EvidenceAnchor:
    """Section 3.2 step 3 for one locked source: the bound anchor, or a refusal.

    The Capture root's lifecycle (`denied` / `capture_withdrawn` when
    archived), the version's classification, a legacy root's point-in-time
    restricted-version refusal (F21/F24), the stored source digest and the
    passage digest. The answer carries the server-derived `source_version_no`.
    Writes nothing.
    """
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
    return _shape_checked(
        anchor,
        source_version_no=None if source is None else source.version_number,
        detail=detail,
    )


def insert_evidence_anchor(
    issues: IssueRepository, principal_id: str, bound: EvidenceAnchor, *, recorded_at: datetime
) -> str:
    """Reuse the anchor with this identity, or insert it; its `anchor_id`."""
    return issues.admit_anchor(
        principal_id,
        bound,
        anchor_id=issue_identifier(IdKind.LINEAGE_EVIDENCE_ANCHOR),
        recorded_at=recorded_at,
    )


def admit_evidence_anchor(
    issues: IssueRepository,
    principal_id: str,
    locked: LockedEvidenceSource,
    *,
    recorded_at: datetime,
    detail: SafeDetail,
) -> str:
    """Section 3.2 step 3 for one locked source, then reuse-or-insert the anchor."""
    bound = bind_evidence_anchor(issues, principal_id, locked, detail=detail)
    return insert_evidence_anchor(issues, principal_id, bound, recorded_at=recorded_at)


# --- record references and evidence sets (section 7.1) -------------------------

#: The admitted keys of one `RecordRef` document (section 7.1).
RECORD_REF_KEYS: Final[frozenset[str]] = frozenset({"family", "record_id"})


def parse_record_ref(document: object, detail: SafeDetail) -> RecordRef:
    """One `RecordRef` from a caller document, or `invalid_request` / `detail`.

    The family is an S1 `RecordFamily` and the identifier carries that
    family's prefix (section 3.2 step 1).
    """
    if not isinstance(document, Mapping) or set(document) != RECORD_REF_KEYS:
        raise InvalidRequestError(detail)
    family = _member(document.get("family"), RecordFamily, detail)
    record_id = document.get("record_id")
    refused = not isinstance(record_id, str)
    if not refused:
        try:
            return RecordRef(family=family, record_id=record_id)  # type: ignore[arg-type]
        except InvalidLineageValueError:
            refused = True
    raise InvalidRequestError(detail)


def _input_identity(anchor: EvidenceAnchorInput) -> tuple[object, ...]:
    """What determines an anchor's `anchor_identity`: every input key but `role`.

    The server-derived `source_version_no` is a function of `version_id`, so
    two inputs equal here have one identity once bound.
    """
    return (
        anchor.family.value,
        anchor.root_id,
        anchor.version_kind.value,
        anchor.version_id,
        anchor.source_sha256,
        anchor.passage_start_cp,
        anchor.passage_end_cp,
        anchor.passage_sha256,
    )


def _input_order(anchor: EvidenceAnchorInput) -> tuple[tuple[int, object], ...]:
    """Section 5.1 order over the input keys, `null` before any value."""
    return tuple(
        (0, 0) if value is None else (1, value)
        for value in (*_input_identity(anchor), anchor.role.value)
    )


def parse_evidence_anchors(
    documents: object, detail: SafeDetail, *, minimum: int
) -> tuple[EvidenceAnchorInput, ...]:
    """An evidence set of `minimum..32` anchors in section 5.1 order.

    A set in which two anchors share an `anchor_identity`, whatever their
    roles, is `invalid_request` / `detail` (section 5.1).
    """
    if not isinstance(documents, tuple | list) or not (
        minimum <= len(documents) <= MAX_EVIDENCE_ANCHORS
    ):
        raise InvalidRequestError(detail)
    parsed = [parse_evidence_anchor(document, detail) for document in documents]
    if len({_input_identity(anchor) for anchor in parsed}) != len(parsed):
        raise InvalidRequestError(detail)
    return tuple(sorted(parsed, key=_input_order))


def anchor_inputs_document(anchors: Sequence[EvidenceAnchorInput]) -> list[dict[str, object]]:
    """The evidence set as the request digest holds it, in section 5.1 order."""
    return [anchor.digest_document() for anchor in sorted(anchors, key=_input_order)]


# --- the relation matrix (section 3.1) -------------------------------------------


def relation_kind(relation: RelationType, from_ref: RecordRef, to_ref: RecordRef) -> RecordLinkKind:
    """The link kind of an admitted `(from, to, relation)`; else `invalid_request`."""
    kind, sources, targets = RELATION_MATRIX[relation]
    if from_ref.family not in sources or to_ref.family not in targets:
        raise InvalidRequestError(SafeDetail.RELATION_TYPE)
    return kind


def _is_exact_origin(anchor: EvidenceAnchor, to_ref: RecordRef) -> bool:
    return (
        anchor.role is EvidenceRole.ORIGIN
        and anchor.source_version_kind is SourceVersionKind.IMMUTABLE_VERSION
        and anchor.source_family.value == to_ref.family.value
        and anchor.passage_start_cp is not None
        and anchor.source_version_id == to_ref.record_id
    )


def _is_discussion_of(anchor: EvidenceAnchor, from_ref: RecordRef) -> bool:
    if (
        anchor.role is not EvidenceRole.DISCUSSION
        or anchor.source_family is not EvidenceSourceFamily.MEETING_NOTE_VERSION
    ):
        return False
    if from_ref.family is RecordFamily.MEETING_NOTE_VERSION:
        return anchor.source_version_id == from_ref.record_id
    return anchor.source_root_id == from_ref.record_id


#: S2 section 3.1: the relations whose rule is "at least one exact-version
#: anchor with this role".
_EXACT_ROLE_RULES: Final[Mapping[RelationType, EvidenceRole]] = {
    RelationType.DELEGATED_FROM: EvidenceRole.ORIGIN,
    RelationType.ESCALATED_FROM: EvidenceRole.ORIGIN,
    RelationType.BLOCKS: EvidenceRole.CORROBORATES,
    # S3 section 3.1.
    RelationType.RELATED_CONTEXT: EvidenceRole.CORROBORATES,
}


def require_relation_evidence(
    relation: RelationType,
    from_ref: RecordRef,
    to_ref: RecordRef,
    anchors: Sequence[EvidenceAnchor],
) -> None:
    """Section 3.1's evidence rule for one relation, or `invalid_request` / `evidence_anchors`.

    `originated_from` needs an `origin` anchor on an exact passage of the `to`
    version; `discusses` a `discussion` note anchor on the `from` note version
    or on a note version of the `from` Meeting. `issue_member` needs none. A
    legacy Capture root never satisfies either rule.

    S2 (section 3.1): `delegated_from` and `escalated_from` need an `origin`
    anchor on an exact version (`immutable_version`), `blocks` a
    `corroborates` one; `created_to_resolve` admits any set. S3 (section 3.1):
    `related_context` needs an exact `corroborates` anchor. This is the rule
    a correction re-applies (R2-F07); the assert-time rules are the
    composite's and `records.associations.assert`'s.
    """
    if relation is RelationType.ORIGINATED_FROM:
        satisfied = any(_is_exact_origin(anchor, to_ref) for anchor in anchors)
    elif relation in _EXACT_ROLE_RULES:
        role = _EXACT_ROLE_RULES[relation]
        satisfied = any(
            anchor.role is role
            and anchor.source_version_kind is SourceVersionKind.IMMUTABLE_VERSION
            for anchor in anchors
        )
    elif relation is RelationType.DISCUSSES:
        satisfied = any(_is_discussion_of(anchor, from_ref) for anchor in anchors)
    else:
        satisfied = True
    if not satisfied:
        raise InvalidRequestError(SafeDetail.EVIDENCE_ANCHORS)


# --- locking in section 6.2 order and linkability (section 3.2) --------------------

_TargetKind = Literal["issue", "endpoint", "capture_root", "evidence"]

#: The family token each kind of lock target sorts under.
_CAPTURE_ROOT_FAMILY: Final = "capture"


@dataclass(frozen=True, slots=True)
class _LockTarget:
    token: str
    identifier: str
    kind: _TargetKind
    refusal: SafeDetail
    ref: RecordRef | None = None
    anchor: EvidenceAnchorInput | None = None

    def order(self) -> tuple[str, str, int]:
        # Within one row, an endpoint share precedes an evidence share; both are
        # `FOR SHARE`, so the second only re-acquires what the first holds.
        rank = {"capture_root": 0, "issue": 1, "endpoint": 1, "evidence": 2}[self.kind]
        return (self.token, self.identifier, rank)


@dataclass(frozen=True, slots=True)
class LockedLineageSources:
    """Everything one link write names, locked and proven to exist (section 3.2 step 2).

    `endpoints` maps each named endpoint to its locked row; `evidence` holds
    one locked source per anchor, in the input order; `issues` maps each
    named Issue (`issue_ids`) to its locked row.
    """

    endpoints: Mapping[RecordRef, LineageEndpoint] = field(default_factory=dict)
    evidence: tuple[LockedEvidenceSource, ...] = ()
    issues: Mapping[str, IssueRecord] = field(default_factory=dict)


def _evidence_targets(anchor: EvidenceAnchorInput, detail: SafeDetail) -> list[_LockTarget]:
    if anchor.family is EvidenceSourceFamily.MEETING_NOTE_VERSION:
        return [
            _LockTarget(
                token=RecordFamily.MEETING_NOTE_VERSION.value,
                identifier=anchor.version_id or "",
                kind="evidence",
                refusal=detail,
                anchor=anchor,
            )
        ]
    targets = [
        _LockTarget(
            token=_CAPTURE_ROOT_FAMILY,
            identifier=anchor.root_id,
            kind="capture_root",
            refusal=detail,
        )
    ]
    if anchor.family is EvidenceSourceFamily.CAPTURE_VERSION:
        targets.append(
            _LockTarget(
                token=RecordFamily.CAPTURE_VERSION.value,
                identifier=anchor.version_id or "",
                kind="evidence",
                refusal=detail,
                anchor=anchor,
            )
        )
    else:
        # A legacy root: the root share is its only lock; this target carries
        # the anchor so its (version-less) locked source is recorded.
        targets.append(
            _LockTarget(
                token=_CAPTURE_ROOT_FAMILY,
                identifier=anchor.root_id,
                kind="evidence",
                refusal=detail,
                anchor=anchor,
            )
        )
    return targets


def lock_lineage_sources(
    issues: IssueRepository,
    lineage: RecordLineageRepository,
    principal_id: str,
    *,
    issue_ids: Sequence[tuple[str, SafeDetail]] = (),
    endpoints: Sequence[tuple[RecordRef, SafeDetail]] = (),
    anchors: Sequence[EvidenceAnchorInput] = (),
    anchor_detail: SafeDetail = SafeDetail.EVIDENCE_ANCHORS,
) -> LockedLineageSources:
    """Section 6.2 step 3: share every named row in `(family token, identifier)` order.

    `issue_ids` are Issues the write does not change (an Issue membership's
    Issue, an association's Issue context): `FOR SHARE` through
    `lock_issue`, so a context Situation or an absent one is `not_found` with
    its detail. `endpoints` are `RecordRef`s shared in their native tables;
    a Capture version endpoint shares its root first. Each absent, foreign or
    wrong-parent target answers `not_found` with its own detail, in lock order.
    """
    targets: list[_LockTarget] = [
        _LockTarget(
            token=RecordFamily.SITUATION.value, identifier=issue_id, kind="issue", refusal=detail
        )
        for issue_id, detail in issue_ids
    ]
    for ref, detail in endpoints:
        if ref.family is RecordFamily.CAPTURE_VERSION:
            root = lineage.capture_version_root(principal_id, ref.record_id)
            if root is None:
                raise NotFoundError(detail)
            targets.append(
                _LockTarget(
                    token=_CAPTURE_ROOT_FAMILY, identifier=root, kind="capture_root", refusal=detail
                )
            )
        targets.append(
            _LockTarget(
                token=ref.family.value,
                identifier=ref.record_id,
                kind="endpoint",
                refusal=detail,
                ref=ref,
            )
        )
    for anchor in anchors:
        targets.extend(_evidence_targets(anchor, anchor_detail))
    locked_endpoints: dict[RecordRef, LineageEndpoint] = {}
    locked_evidence: dict[int, LockedEvidenceSource] = {}
    locked_issues: dict[str, IssueRecord] = {}
    for target in sorted(targets, key=_LockTarget.order):
        if target.kind == "issue":
            issue = issues.lock_issue(principal_id, target.identifier, for_update=False)
            if issue is None:
                raise NotFoundError(target.refusal)
            locked_issues[target.identifier] = issue
        elif target.kind == "capture_root":
            if not issues.share_capture_root(principal_id, target.identifier):
                raise NotFoundError(target.refusal)
        elif target.kind == "endpoint" and target.ref is not None:
            endpoint = lineage.share_endpoint(principal_id, target.ref.family, target.identifier)
            if endpoint is None:
                raise NotFoundError(target.refusal)
            locked_endpoints[target.ref] = endpoint
        elif target.anchor is not None:
            locked_evidence[id(target.anchor)] = _lock_one_source(
                issues, principal_id, target.anchor, target.refusal
            )
    return LockedLineageSources(
        endpoints=locked_endpoints,
        evidence=tuple(locked_evidence[id(anchor)] for anchor in anchors),
        issues=locked_issues,
    )


def require_open_issues(locked: LockedLineageSources) -> None:
    """S2 section 3.2: no lineage write names a closed Issue (`conflict` / `state`).

    Called once every target is locked and proven to exist, so an absent or
    foreign closed Issue has already answered `not_found`. Covers the Issues a
    write names (an owner or a context) and every Situation endpoint.
    """
    closed = SituationState.CLOSED.value
    if any(issue.state is SituationState.CLOSED for issue in locked.issues.values()) or any(
        endpoint.family is RecordFamily.SITUATION and endpoint.situation_state == closed
        for endpoint in locked.endpoints.values()
    ):
        raise ConflictError(SafeDetail.STATE)


def _lock_one_source(
    issues: IssueRepository, principal_id: str, anchor: EvidenceAnchorInput, detail: SafeDetail
) -> LockedEvidenceSource:
    """One anchor's version share; its Capture root is already shared in order."""
    if anchor.family is EvidenceSourceFamily.MEETING_NOTE_VERSION:
        note = issues.share_note_version(principal_id, anchor.root_id, anchor.version_id or "")
        if note is None:
            raise NotFoundError(detail)
        return LockedEvidenceSource(anchor=anchor, version=note)
    if anchor.family is EvidenceSourceFamily.CAPTURE_VERSION:
        version = issues.share_capture_version(
            principal_id, anchor.root_id, anchor.version_id or ""
        )
        if version is None:
            raise NotFoundError(detail)
        return LockedEvidenceSource(anchor=anchor, version=version)
    return LockedEvidenceSource(anchor=anchor, version=None)


def require_linkable(issues: IssueRepository, principal_id: str, endpoint: LineageEndpoint) -> None:
    """Section 3.2 step 3 for one locked endpoint (only after every existence check)."""
    if endpoint.family is RecordFamily.SITUATION:
        if endpoint.situation_kind is not SituationKind.ISSUE_WORKSTREAM:
            raise InvalidRequestError(SafeDetail.ENDPOINT)
    elif endpoint.family is RecordFamily.TASK:
        if endpoint.task_archived:
            raise InvalidRequestError(SafeDetail.ENDPOINT)
    elif endpoint.family is RecordFamily.CAPTURE_VERSION:
        if endpoint.capture_id is None:
            raise InvalidRequestError(SafeDetail.ENDPOINT)
        if issues.capture_root_is_archived(principal_id, endpoint.capture_id):
            raise DeniedError(SafeDetail.CAPTURE_WITHDRAWN)
        if endpoint.classification not in _ADMITTED_CLASSIFICATIONS:
            raise InvalidRequestError(SafeDetail.ENDPOINT)


def admit_evidence_set(
    issues: IssueRepository,
    principal_id: str,
    locked: Sequence[LockedEvidenceSource],
    *,
    detail: SafeDetail = SafeDetail.EVIDENCE_ANCHORS,
) -> tuple[EvidenceAnchor, ...]:
    """Bind every locked anchor (section 3.2 step 3) and order the set (section 5.1).

    Writes nothing: the caller inserts the anchors, in this order, once every
    other check has passed. A repeated `anchor_identity` is `invalid_request`.
    """
    bound = [bind_evidence_anchor(issues, principal_id, source, detail=detail) for source in locked]
    refused = False
    try:
        return canonical_evidence(bound)
    except DuplicateAnchorIdentityError:
        refused = True
    if refused:
        raise InvalidRequestError(detail)
    raise AssertionError("unreachable")  # pragma: no cover
