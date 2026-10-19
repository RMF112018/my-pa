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

Every value in a source document is an identifier, a closed token, an integer,
a boolean or a hex digest, so the document is ASCII and NFC is the identity:
`source_document` refuses anything else rather than normalize it.

The classification table (section 8.3) is the backfill package's, not this
module's: this module classifies nothing.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, parse_identifier
from my_pa.domain.lineage.canonical import canonical_json
from my_pa.domain.lineage.model import InvalidLineageValueError
from my_pa.domain.lineage_backfill.vocabulary import BackfillSourceKind

__all__ = [
    "PLAN_DOMAIN",
    "SOURCE_DOMAIN",
    "SOURCE_FACT_KEYS",
    "SOURCE_FAMILIES",
    "SPAN_FACT_KEYS",
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
