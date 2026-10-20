"""The backfill dry run's pure encodings, record lineage S3 contract sections 4.2, 5 and 8.3.

Pure. A backfill run freezes a population of native facts and classifies each
item; this module states the byte encodings both halves of that agree on:

* **the reference token** (section 4.2, R3-F22): a work item's
  `origin_evidence_ref` (or a context Situation's object ref) is stored in the
  ledger as an ASCII token -- an identifier-shaped reference as itself, any
  other as `<shape>:<sha256 hex of the UTF-8 bytes of the exact stored text>`,
  where `<shape>` is `prefix:<IdKind prefix>` for an identifier of a kind the
  backfill does not interpret and `free_text` otherwise. The text itself is
  never stored, digested in any other form, or displayed.
* **the source document and digest** (section 5): the canonical JSON of one
  item's native facts and its `sha256(b"lineage-backfill-source-v1\\n" +
  document)`. The database computes both in the enumerating statement
  (`knowledge.lineage_backfill_source_document` and
  `knowledge.lineage_backfill_source_digest`, frozen in the S3 revision);
  `source_document` here is their mirror, held to them by shared golden vectors
  (`tests/fixtures/lineage_backfill_source_vectors.json`).
* **the plan digest** (section 5) over a classified run's items.
* **the classification table** (section 8.3, `classify`): one item's class,
  reason and candidate link, a pure function of its stored source document --
  plus, for a `work_origin_assertion` candidate, the cited Capture version's
  immutable identity (`CaptureVersionPin`: root, number, content digest, which
  an S1 anchor object needs and the document does not carry), and for a
  `situation_object_ref`, whether the referenced record is owned by the
  Principal (`owned_reference`; the frozen fact set carries only the
  Situation's `object_refs` digest).

Every value in a source document is an identifier, a closed token, an integer,
a boolean or a hex digest, so the document is ASCII and NFC is the identity:
`source_document` refuses anything else rather than normalize it. No item is
ever derived from words, names, a shared Project, Series, participant or date
(OD-05): the table reads only the closed facts of `SOURCE_FACT_KEYS`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, parse_identifier
from my_pa.domain.lineage.canonical import (
    anchor_object,
    canonical_evidence,
    canonical_json,
    normalized_identity,
)
from my_pa.domain.lineage.model import EvidenceAnchor, InvalidLineageValueError, RecordRef
from my_pa.domain.lineage.vocabulary import (
    RECORD_FAMILY_ID_KINDS,
    EvidenceRole,
    EvidenceSourceFamily,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SituationKind,
    SourceVersionKind,
)
from my_pa.domain.lineage_backfill.vocabulary import (
    BackfillClass,
    BackfillReason,
    BackfillSourceKind,
)

__all__ = [
    "MAX_CANDIDATE_SPANS",
    "PLAN_DOMAIN",
    "QUARANTINED_CLASSES",
    "SOURCE_DOMAIN",
    "SOURCE_FACT_KEYS",
    "SOURCE_FAMILIES",
    "SPAN_FACT_KEYS",
    "BackfillCandidate",
    "BackfillClassification",
    "CaptureVersionPin",
    "classify",
    "lineage_family_of_reference",
    "object_reference",
    "origin_reference",
    "plan_digest",
    "reference_token",
    "source_digest",
    "source_document",
]

#: Domain separator of the source digest (section 5).
SOURCE_DOMAIN: Final = b"lineage-backfill-source-v1\n"
#: Domain separator of the plan digest (section 5).
PLAN_DOMAIN: Final = b"lineage-backfill-plan-v1\n"

_SCHEMA_VERSION: Final = 1
_MAX_TOKEN: Final = 256
_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")

#: The source family each source kind names (section 8.3's population column).
SOURCE_FAMILIES: Final[Mapping[BackfillSourceKind, frozenset[str]]] = MappingProxyType(
    {
        BackfillSourceKind.TASK_FOLLOW_UP: frozenset({"task"}),
        BackfillSourceKind.CONSTRAINT_FOLLOW_UP: frozenset({"constraint"}),
        BackfillSourceKind.MEETING_SERIES: frozenset({"meeting"}),
        BackfillSourceKind.PROJECT_SITUATION: frozenset({"situation"}),
        BackfillSourceKind.WORK_ORIGIN_ASSERTION: frozenset({"task", "commitment"}),
        BackfillSourceKind.WORK_ORIGIN_CAPTURE_ROOT: frozenset({"task", "commitment"}),
        BackfillSourceKind.WORK_ORIGIN_OTHER: frozenset({"task", "commitment"}),
        BackfillSourceKind.SITUATION_OBJECT_REF: frozenset({"situation"}),
    }
)

#: The closed fact object of each source kind (section 8.3): exactly the native
#: values its classification reads, read by the SQL function at the snapshot.
#:
#: * `task_follow_up`: the Task's current `commitment_id`.
#: * `constraint_follow_up`: whether the `follow_up_of` relationship from the
#:   source Constraint to the referenced one still exists.
#: * the Meeting Series kind: the Meeting's current Series identifier.
#: * `project_situation`: the Situation's kind in the Principal, the Principal
#:   that holds the Situation and the one that holds the Project (by
#:   identifier, in any partition), whether the `project_situations` triplet
#:   exists and whether its membership-event ledger has an event.
#: * `work_origin_assertion`: the work row's current reference digest; the
#:   assertion's state, successor and version in the Principal; the version's
#:   classification and its Capture root's lifecycle state; and each cited
#:   span (`SPAN_FACT_KEYS`), ordered by `span_id`.
#: * `work_origin_capture_root`, `work_origin_other`: the work row's current
#:   reference digest only.
#: * `situation_object_ref`: the Situation's kind and the digest of its current
#:   `object_refs` text.
SOURCE_FACT_KEYS: Final[Mapping[BackfillSourceKind, frozenset[str]]] = MappingProxyType(
    {
        BackfillSourceKind.TASK_FOLLOW_UP: frozenset({"commitment_id"}),
        BackfillSourceKind.CONSTRAINT_FOLLOW_UP: frozenset({"relationship_present"}),
        BackfillSourceKind.MEETING_SERIES: frozenset({"series_id"}),
        BackfillSourceKind.PROJECT_SITUATION: frozenset(
            {
                "has_membership_event",
                "link_present",
                "project_principal_id",
                "situation_kind",
                "situation_principal_id",
            }
        ),
        BackfillSourceKind.WORK_ORIGIN_ASSERTION: frozenset(
            {
                "assertion_state",
                "origin_ref_sha256",
                "root_lifecycle_state",
                "spans",
                "superseded_by_assertion_id",
                "version_classification",
                "version_id",
            }
        ),
        BackfillSourceKind.WORK_ORIGIN_CAPTURE_ROOT: frozenset({"origin_ref_sha256"}),
        BackfillSourceKind.WORK_ORIGIN_OTHER: frozenset({"origin_ref_sha256"}),
        BackfillSourceKind.SITUATION_OBJECT_REF: frozenset(
            {"object_refs_sha256", "situation_kind"}
        ),
    }
)

#: One cited span's facts (`work_origin_assertion`): its identity, its version,
#: its offsets and basis, its processing text, its recorded digest and the
#: digest of the slice re-derived from the version's content (`null` when the
#: offsets lie outside it).
SPAN_FACT_KEYS: Final = frozenset(
    {
        "derived_sha256",
        "end_offset",
        "offset_basis",
        "processing_text_id",
        "quoted_text_sha256",
        "span_id",
        "start_offset",
        "version_id",
    }
)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reference_token(reference: str) -> str:
    """The ledger token of a reference the backfill does not interpret (section 4.2).

    An identifier of any `IdKind` becomes `prefix:<prefix>:<digest>`; anything
    else `free_text:<digest>`, the digest being SHA-256 of the exact UTF-8
    bytes of the stored text, with no normalization -- exactly
    `encode(sha256(convert_to(ref, 'UTF8')), 'hex')` in SQL.
    """
    digest = _sha256_hex(reference)
    try:
        kind, _ = parse_identifier(reference)
    except InvalidIdentifierError:
        return f"free_text:{digest}"
    return f"prefix:{kind.value}:{digest}"


def origin_reference(reference: str) -> tuple[BackfillSourceKind, str]:
    """`(source kind, source_ref)` of a work row's `origin_evidence_ref` (section 8.3).

    Population is assigned by identifier shape, not by prefix (R3-F27): a
    whole `asrt_` identifier is a `work_origin_assertion`, a whole `cap_` one a
    `work_origin_capture_root`, each stored as itself; anything else --
    another kind's identifier, free text, or text that merely begins `asrt_`
    or `cap_` -- is `work_origin_other`, stored as its `reference_token`.
    """
    try:
        kind, _ = parse_identifier(reference)
    except InvalidIdentifierError:
        kind = None
    if kind is IdKind.ASSERTION:
        return BackfillSourceKind.WORK_ORIGIN_ASSERTION, reference
    if kind is IdKind.CAPTURE:
        return BackfillSourceKind.WORK_ORIGIN_CAPTURE_ROOT, reference
    return BackfillSourceKind.WORK_ORIGIN_OTHER, reference_token(reference)


def object_reference(reference: str) -> str:
    """The `source_ref` of one element of a context Situation's `object_refs` (section 4.2).

    An identifier of any `IdKind` is stored as itself (its kind decides the
    classification); anything else as `free_text:<sha256 of its exact UTF-8
    text>`, never the text. A non-string JSON element is tokenized from its
    JSON text.
    """
    try:
        parse_identifier(reference)
    except InvalidIdentifierError:
        return f"free_text:{_sha256_hex(reference)}"
    return reference


def _ascii(value: str, what: str) -> str:
    if not value.isascii():
        raise InvalidLineageValueError(f"a backfill source document holds ASCII only ({what})")
    return value


def _fact(value: object, where: str) -> object:
    """One fact value, checked: ASCII text, an integer, a boolean, null, or a span list."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return _ascii(value, where)
    raise InvalidLineageValueError(f"a backfill fact is a token, integer or boolean ({where})")


def _spans(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise InvalidLineageValueError("a backfill span fact is a list")
    checked: list[dict[str, object]] = []
    for span in value:
        if not isinstance(span, Mapping) or set(span) != SPAN_FACT_KEYS:
            raise InvalidLineageValueError("a backfill span fact has exactly its keys")
        checked.append({key: _fact(span[key], f"spans.{key}") for key in sorted(span)})
    identifiers = [str(span["span_id"]) for span in checked]
    if identifiers != sorted(identifiers):
        raise InvalidLineageValueError("backfill span facts are ordered by span_id")
    return checked


def source_document(
    *,
    source_kind: BackfillSourceKind,
    source_family: str,
    source_id: str,
    source_ref: str,
    source_version: int | None,
    facts: Mapping[str, object],
) -> str:
    """The section 5 source document, byte for byte what the SQL function returns."""
    kind = BackfillSourceKind(source_kind)
    if source_family not in SOURCE_FAMILIES[kind]:
        raise InvalidLineageValueError("a backfill source names its kind's family")
    if not 1 <= len(source_ref) <= _MAX_TOKEN:
        raise InvalidLineageValueError("a backfill source_ref is a bounded token")
    if set(facts) != SOURCE_FACT_KEYS[kind]:
        raise InvalidLineageValueError("a backfill source carries exactly its kind's facts")
    checked: dict[str, object] = {}
    for key in sorted(facts):
        value = facts[key]
        checked[key] = _spans(value) if key == "spans" else _fact(value, key)
    if source_version is not None and (isinstance(source_version, bool) or source_version < 1):
        raise InvalidLineageValueError("a backfill source version is positive")
    return canonical_json(
        {
            "facts": checked,
            "schema_version": _SCHEMA_VERSION,
            "source_family": _ascii(source_family, "source_family"),
            "source_id": _ascii(source_id, "source_id"),
            "source_kind": kind.value,
            "source_ref": _ascii(source_ref, "source_ref"),
            "source_version": source_version,
        }
    )


def source_digest(
    *,
    source_kind: BackfillSourceKind,
    source_family: str,
    source_id: str,
    source_ref: str,
    source_version: int | None,
    facts: Mapping[str, object],
) -> str:
    """`sha256(b"lineage-backfill-source-v1\\n" + document)`, lowercase hex."""
    document = source_document(
        source_kind=source_kind,
        source_family=source_family,
        source_id=source_id,
        source_ref=source_ref,
        source_version=source_version,
        facts=facts,
    )
    return hashlib.sha256(SOURCE_DOMAIN + document.encode("utf-8")).hexdigest()


def plan_digest(
    *,
    run_id: str,
    validator_version: int,
    items: Sequence[tuple[int, str, str, str, str | None]],
) -> str:
    """The section 5 plan digest over `(item_no, source_digest, class, reason, candidate)`.

    `items` must already be in `item_no` order; each `source_digest` is hex.
    """
    numbers = [item[0] for item in items]
    if numbers != sorted(numbers) or len(set(numbers)) != len(numbers):
        raise InvalidLineageValueError("plan items are in strictly increasing item_no order")
    for item in items:
        if not _SHA256_HEX.fullmatch(item[1]):
            raise InvalidLineageValueError("a plan item's source digest is sha256 hex")
    document = canonical_json(
        {
            "items": [list(item) for item in items],
            "run_id": _ascii(run_id, "run_id"),
            "schema_version": _SCHEMA_VERSION,
            "validator_version": validator_version,
        }
    )
    return hashlib.sha256(PLAN_DOMAIN + document.encode("utf-8")).hexdigest()


# --- the classification table (section 8.3) ---------------------------------------

#: At most this many cited spans make one candidate's evidence set (S1 admission).
MAX_CANDIDATE_SPANS: Final = 32
#: The classes whose items are quarantined (section 8.3).
QUARANTINED_CLASSES: Final = frozenset({BackfillClass.UNRESOLVED, BackfillClass.REFUSED})

#: The native tokens the classification compares against, spelled here rather
#: than imported from the Capture plane (a pure lineage module); the unit test
#: holds each to its enum.
ACCEPTED_ASSERTION_STATE: Final = "accepted"
ACTIVE_CAPTURE_ROOT_STATE: Final = "active"
EXACT_OFFSET_BASIS: Final = "unicode_code_point_v1"
#: A Capture version an S1 link may name (`application.lineage_endpoints`).
_LINKABLE_CLASSIFICATIONS: Final = frozenset(
    {Classification.SYNTHETIC_TEST.value, Classification.PRIVATE_LOCAL.value}
)
#: The `IdKind` of each lineage record family, inverted: an object ref of one of
#: these kinds names a lineage record.
_LINEAGE_FAMILY_OF_KIND: Final[Mapping[IdKind, RecordFamily]] = MappingProxyType(
    {kind: family for family, kind in RECORD_FAMILY_ID_KINDS.items()}
)
_WORK_FAMILIES: Final[Mapping[str, RecordFamily]] = MappingProxyType(
    {"task": RecordFamily.TASK, "commitment": RecordFamily.COMMITMENT}
)


@dataclass(frozen=True, slots=True)
class CaptureVersionPin:
    """A cited Capture version's immutable identity: its root, number and content digest."""

    version_id: str
    capture_id: str
    version_number: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class BackfillCandidate:
    """The link an item would materialize: endpoints, relation, and its anchor objects.

    `identity` is its S1 section 5.3 `normalized_identity` (null context: the
    backfill names no Issue); `document` the canonical JSON the ledger stores.
    """

    from_ref: RecordRef
    relation_type: RelationType
    to_ref: RecordRef
    identity: str
    document: str


@dataclass(frozen=True, slots=True)
class BackfillClassification:
    """One item's settled class, reason and candidate (section 8.3)."""

    classification: BackfillClass
    reason: BackfillReason
    candidate: BackfillCandidate | None = None

    @property
    def quarantined(self) -> bool:
        """`unresolved` and `refused` items are quarantined."""
        return self.classification in QUARANTINED_CLASSES


def _settled(classification: BackfillClass, reason: BackfillReason) -> BackfillClassification:
    return BackfillClassification(classification=classification, reason=reason)


def _unresolvable() -> BackfillClassification:
    return _settled(BackfillClass.UNRESOLVED, BackfillReason.REFERENCE_UNRESOLVABLE)


def _origin_candidate(
    work: RecordRef, pin: CaptureVersionPin, spans: Sequence[Mapping[str, object]]
) -> BackfillCandidate:
    """`work originated_from capture_version`, one `origin` anchor per qualifying span."""
    to_ref = RecordRef(family=RecordFamily.CAPTURE_VERSION, record_id=pin.version_id)
    anchors = canonical_evidence(
        {
            EvidenceAnchor(
                source_family=EvidenceSourceFamily.CAPTURE_VERSION,
                source_root_id=pin.capture_id,
                source_version_kind=SourceVersionKind.IMMUTABLE_VERSION,
                source_version_id=pin.version_id,
                source_version_no=pin.version_number,
                source_sha256=pin.content_sha256,
                passage_start_cp=int(str(span["start_offset"])),
                passage_end_cp=int(str(span["end_offset"])),
                passage_sha256=str(span["quoted_text_sha256"]),
                role=EvidenceRole.ORIGIN,
            )
            for span in spans
        }
    )
    identity = normalized_identity(
        kind=RecordLinkKind.SEMANTIC,
        relation_type=RelationType.ORIGINATED_FROM,
        from_ref=work,
        to_ref=to_ref,
        member_role=None,
        context_issue_id=None,
    )
    document = canonical_json(
        {**json.loads(identity), "evidence": [anchor_object(anchor) for anchor in anchors]}
    )
    return BackfillCandidate(
        from_ref=work,
        relation_type=RelationType.ORIGINATED_FROM,
        to_ref=to_ref,
        identity=identity,
        document=document,
    )


def _qualifies(span: Mapping[str, object], version_id: object) -> bool:
    """A cited span proves its passage: original text, code points, the exact version."""
    start, end = span["start_offset"], span["end_offset"]
    return (
        span["processing_text_id"] is None
        and span["offset_basis"] == EXACT_OFFSET_BASIS
        and span["version_id"] == version_id
        and isinstance(start, int)
        and isinstance(end, int)
        and not isinstance(start, bool)
        and not isinstance(end, bool)
        and 0 <= start < end
        and span["derived_sha256"] is not None
        and span["derived_sha256"] == span["quoted_text_sha256"]
    )


def _assertion(
    source: Mapping[str, object], facts: Mapping[str, object], pin: CaptureVersionPin | None
) -> BackfillClassification:
    version_id = facts["version_id"]
    if facts["assertion_state"] is None or version_id is None:
        return _unresolvable()
    if (
        facts["assertion_state"] != ACCEPTED_ASSERTION_STATE
        or facts["superseded_by_assertion_id"] is not None
    ):
        return _settled(BackfillClass.REFUSED, BackfillReason.ASSERTION_NOT_CURRENT)
    if facts["version_classification"] is None or pin is None or pin.version_id != version_id:
        return _unresolvable()
    if facts["root_lifecycle_state"] != ACTIVE_CAPTURE_ROOT_STATE:
        return _settled(BackfillClass.REFUSED, BackfillReason.SOURCE_WITHDRAWN)
    if facts["version_classification"] not in _LINKABLE_CLASSIFICATIONS:
        return _settled(BackfillClass.REFUSED, BackfillReason.SOURCE_RESTRICTED)
    spans = facts["spans"]
    if not isinstance(spans, list):
        raise InvalidLineageValueError("a backfill span fact is a list")
    qualifying = [span for span in spans if _qualifies(span, version_id)]
    work = RecordRef(
        family=_WORK_FAMILIES[str(source["source_family"])], record_id=str(source["source_id"])
    )
    if 1 <= len(qualifying) <= MAX_CANDIDATE_SPANS:
        return BackfillClassification(
            classification=BackfillClass.SOURCE_BACKED_ACCEPTED,
            reason=BackfillReason.EXACT_ORIGINAL_SPAN,
            candidate=_origin_candidate(work, pin, qualifying),
        )
    # The version is exact, the passage is not proven: the link is derivable and
    # carries no anchor (the operator's review asserts with evidence).
    return BackfillClassification(
        classification=BackfillClass.REVIEW_CANDIDATE,
        reason=BackfillReason.PASSAGE_UNPROVEN,
        candidate=_origin_candidate(work, pin, ()),
    )


def _project_situation(principal_id: str, facts: Mapping[str, object]) -> BackfillClassification:
    kind = facts["situation_kind"]
    consistent = (
        kind is not None
        and facts["situation_principal_id"] == principal_id
        and facts["project_principal_id"] == principal_id
        and facts["link_present"] is True
        and (kind != SituationKind.ISSUE_WORKSTREAM.value or facts["has_membership_event"] is True)
    )
    if consistent:
        return _settled(
            BackfillClass.NATIVE_VIRTUAL_PROVEN, BackfillReason.NATIVE_PROJECT_SITUATION
        )
    return _settled(BackfillClass.UNRESOLVED, BackfillReason.PROJECT_SITUATION_INCONSISTENT)


def lineage_family_of_reference(reference: str) -> RecordFamily | None:
    """The lineage family an object ref's identifier names, or `None`."""
    try:
        kind, _ = parse_identifier(reference)
    except InvalidIdentifierError:
        return None
    return _LINEAGE_FAMILY_OF_KIND.get(kind)


def classify(
    document: str,
    *,
    principal_id: str,
    pin: CaptureVersionPin | None = None,
    owned_reference: bool = False,
) -> BackfillClassification:
    """Section 8.3's classification of one unchanged source, from its stored document.

    `document` is the source document the database rebuilt for the item (its
    digest already equal to the stored one; a changed source is the caller's
    `unresolved` / `source_changed`). `pin` is the cited Capture version of a
    `work_origin_assertion`; `owned_reference` says whether a
    `situation_object_ref` names a record the Principal owns. Nothing else is
    read: no words, names, Projects, Series, participants or dates.
    """
    source = json.loads(document)
    if not isinstance(source, dict) or source.get("schema_version") != _SCHEMA_VERSION:
        raise InvalidLineageValueError("a backfill source document is a v1 object")
    kind = BackfillSourceKind(source["source_kind"])
    facts = source["facts"]
    if not isinstance(facts, dict) or set(facts) != SOURCE_FACT_KEYS[kind]:
        raise InvalidLineageValueError("a backfill source carries exactly its kind's facts")
    if kind is BackfillSourceKind.TASK_FOLLOW_UP:
        if facts["commitment_id"] is None:
            return _unresolvable()
        return _settled(BackfillClass.NATIVE_VIRTUAL_PROVEN, BackfillReason.NATIVE_FOLLOW_UP)
    if kind is BackfillSourceKind.CONSTRAINT_FOLLOW_UP:
        if facts["relationship_present"] is not True:
            return _unresolvable()
        return _settled(
            BackfillClass.NATIVE_VIRTUAL_PROVEN, BackfillReason.NATIVE_CONSTRAINT_FOLLOW_UP
        )
    if kind is BackfillSourceKind.MEETING_SERIES:
        if facts["series_id"] is None:
            return _unresolvable()
        return _settled(BackfillClass.NATIVE_VIRTUAL_PROVEN, BackfillReason.NATIVE_MEETING_SERIES)
    if kind is BackfillSourceKind.PROJECT_SITUATION:
        return _project_situation(principal_id, facts)
    if kind is BackfillSourceKind.WORK_ORIGIN_ASSERTION:
        return _assertion(source, facts, pin)
    if kind is BackfillSourceKind.WORK_ORIGIN_CAPTURE_ROOT:
        # A root pins no version (S1 section 3.1).
        return _settled(BackfillClass.UNRESOLVED, BackfillReason.NO_EXACT_VERSION)
    if kind is BackfillSourceKind.WORK_ORIGIN_OTHER:
        # Counted, never interpreted.
        return _settled(BackfillClass.UNRESOLVED, BackfillReason.ORIGIN_REF_UNSUPPORTED)
    # situation_object_ref: an owned lineage record is a review candidate, never accepted.
    reference = str(source["source_ref"])
    if lineage_family_of_reference(reference) is not None and owned_reference:
        return _settled(BackfillClass.REVIEW_CANDIDATE, BackfillReason.OBJECT_REF_UNPROVEN)
    return _unresolvable()
