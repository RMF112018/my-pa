"""KLP-WP-03: the Knowledge Assertion read/create use cases' pure core.

Everything here is decided without I/O: who counts as remote, whether an
explicit create is admissible for a predicate, the typed candidate, the frozen
request digest (`domain.knowledge_assertion.digest`, never re-implemented), the
keyset cursor and the public views. `ApplicationService` owns the transaction
and hands the repository what this module derives.

**Explicit-create admissibility** (R6 is silent; the most restrictive reading,
recorded as deviations in the WP-03 evidence):

* the predicate must be the active head of a registered code;
* a predicate whose canonical owner is not the Knowledge plane completes as
  `domain_owned_no_intake` naming that owner and writes no assertion -- WP-03
  routes nothing to another plane;
* a consequential predicate, or one that requires operator review, is refused
  `invalid_request(review_required)` before any subject or evidence is read,
  so the refusal writes no row and is no existence oracle -- otherwise a
  remote ChatLLM create would bypass the operator-review rule;
* evidence is Capture or Relationship Memory only, never counterevidence
  (the command refuses the rest), and no excerpt is stored;
* explicit create carries no owner reference.

The epistemic status is always `principal_asserted`, the class at least
`private_local` (never `synthetic_test`), and the actor/authority of its Record
Event `principal` / `user_confirmed_assertion` -- all server-derived.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime
from typing import Any, Final

from my_pa.application.authorization import Authorization
from my_pa.application.commands import CreateKnowledgeAssertion, SubmitKnowledgeAssertion
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.ports import (
    KnowledgeAssertionHistory,
    KnowledgeAssertionPage,
    KnowledgeAssertionReveal,
    KnowledgeAssertionRow,
    KnowledgeCreateEvidence,
    KnowledgeCreateRequest,
    KnowledgeSubmissionResult,
)
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.knowledge_assertion.admission import AdmissionEvidence
from my_pa.domain.knowledge_assertion.assertion import (
    InvalidKnowledgeAssertionError,
    KnowledgeAssertionCandidate,
    KnowledgeValue,
    validate_qualifier,
    validate_subject,
)
from my_pa.domain.knowledge_assertion.digest import (
    DigestEvidence,
    InvalidKnowledgeValueError,
    request_digest,
    request_digest_object,
)
from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.vocabulary import (
    LIVE_ASSERTION_LIFECYCLES,
    KnowledgeAssertionLifecycle,
    KnowledgeCanonicalOwner,
    KnowledgeConsequentialClass,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeOriginSystem,
    KnowledgeReviewRequirement,
    KnowledgeValueType,
)

__all__ = [
    "DEFAULT_KNOWLEDGE_PAGE_SIZE",
    "KNOWLEDGE_TRUST_BASIS",
    "assertion_view",
    "create_request",
    "decode_knowledge_cursor",
    "encode_knowledge_cursor",
    "history_view",
    "is_remote",
    "lifecycles_for",
    "page_view",
    "reveal_view",
    "submission_view",
    "submit_admission_evidence",
]

#: The page size when the caller names none.
DEFAULT_KNOWLEDGE_PAGE_SIZE: Final = 25
#: What a Knowledge answer's trust rests on: the Principal's own partition.
KNOWLEDGE_TRUST_BASIS: Final = ("principal_partition",)

_CURSOR_ALPHABET: Final = re.compile(r"\A[A-Za-z0-9_-]{1,512}\Z")
_ASSERTION_ID: Final = re.compile(r"\Akasr_[A-Za-z0-9]{8,64}\Z")


def is_remote(authorization: Authorization) -> bool:
    """R6 section 5.2 (KLP-R6V-102): a remote transport or any grant ceiling.

    Fails closed: a composition that attached a grant set is remote even over a
    LOCAL transport (gsqs_b0 stdio), and a REMOTE_CLIENT transport is remote
    even with no grant set.
    """
    return (
        authorization.transport is CaptureTransport.REMOTE_CLIENT
        or authorization.capability_grants is not None
    )


def lifecycles_for(lifecycle: KnowledgeAssertionLifecycle | None) -> frozenset[str]:
    """One named lifecycle, or the live pair when none is named."""
    if lifecycle is None:
        return frozenset(member.value for member in LIVE_ASSERTION_LIFECYCLES)
    return frozenset({lifecycle.value})


# --- explicit create -----------------------------------------------------------


def _value(predicate: KnowledgePredicate, raw: str) -> KnowledgeValue:
    try:
        if predicate.value_type is KnowledgeValueType.TEXT:
            return KnowledgeValue.text(raw)
        parsed: datetime | None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
        if parsed is None:
            raise InvalidKnowledgeValueError("a datetime value must be RFC 3339")
        return KnowledgeValue.instant(parsed)
    except (InvalidKnowledgeValueError, InvalidKnowledgeAssertionError):
        pass
    raise InvalidRequestError(SafeDetail.RAW_VALUE)


def _candidate(
    command: CreateKnowledgeAssertion, predicate: KnowledgePredicate
) -> KnowledgeAssertionCandidate:
    """The typed candidate, refusing each field by name and never echoing it."""
    if command.subject_kind not in predicate.allowed_subject_kinds:
        raise InvalidRequestError(SafeDetail.SUBJECT)
    try:
        validate_subject(command.subject_kind, command.subject_id)
    except InvalidKnowledgeAssertionError:
        raise InvalidRequestError(SafeDetail.SUBJECT) from None
    try:
        validate_qualifier(predicate.qualifier_rule, command.qualifier)
    except InvalidKnowledgeAssertionError:
        raise InvalidRequestError(SafeDetail.STRUCTURED_VALUE) from None
    value = _value(predicate, command.value)
    if (
        command.effective_from is not None
        and command.effective_to is not None
        and not command.effective_to > command.effective_from
    ):
        raise InvalidRequestError(SafeDetail.EFFECTIVE_TO)
    try:
        return KnowledgeAssertionCandidate(
            subject_kind=command.subject_kind,
            subject_id=command.subject_id,
            predicate=predicate,
            value=value,
            qualifier=command.qualifier,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
        )
    except (InvalidKnowledgeAssertionError, InvalidKnowledgeValueError):
        pass
    raise InvalidRequestError(SafeDetail.EFFECTIVE_FROM)


def _evidence(command: CreateKnowledgeAssertion) -> tuple[KnowledgeCreateEvidence, ...]:
    cited: list[KnowledgeCreateEvidence] = []
    for item in command.evidence:
        kind = KnowledgeEvidenceIdentityKind(str(item["identity_kind"]))
        capture = kind is KnowledgeEvidenceIdentityKind.CAPTURE
        cited.append(
            KnowledgeCreateEvidence(
                identity_kind=kind.value,
                content_hash=str(item["content_hash"]),
                role=KnowledgeEvidenceRole(str(item["role"])).value,
                capture_id=str(item["capture_id"]) if capture else None,
                relationship_memory_id=None if capture else str(item["relationship_memory_id"]),
            )
        )
    return tuple(cited)


def create_request(
    command: CreateKnowledgeAssertion,
    predicate: KnowledgePredicate | None,
    *,
    authenticated_client_id: str | None,
) -> KnowledgeCreateRequest:
    """Everything the create transaction needs, or a refusal that writes nothing.

    Every refusal here precedes any subject, evidence or ledger read, so none
    of them can say whether a subject or a version exists.
    """
    if predicate is None or not predicate.is_open_for_intake:
        raise InvalidRequestError(SafeDetail.KINDS)
    domain_owned = predicate.canonical_owner is not KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION
    if not domain_owned and (
        predicate.consequential_class is not KnowledgeConsequentialClass.NONE
        or predicate.review_requirement is not KnowledgeReviewRequirement.REQUIRES_REVIEW
    ):
        raise InvalidRequestError(SafeDetail.REVIEW_REQUIRED)
    candidate = _candidate(command, predicate)
    evidence = _evidence(command)
    digest = request_digest(
        request_digest_object(
            subject_kind=candidate.subject_kind.value,
            subject_id=candidate.subject_id,
            predicate_code=predicate.predicate_code,
            value_type=candidate.value.value_type,
            normalized_value=candidate.value.normalized,
            qualifier=candidate.qualifier,
            effective_from=candidate.effective_from,
            effective_to=candidate.effective_to,
            owner_ref=None,
            source_profile_id=None,
            scope_digest=None,
            trigger_event_ids=(),
            evidence=tuple(
                DigestEvidence(
                    identity_kind=KnowledgeEvidenceIdentityKind(item.identity_kind),
                    identity=(str(item.capture_id or item.relationship_memory_id),),
                    content_hash=item.content_hash,
                    excerpt_sha256=None,
                    role=KnowledgeEvidenceRole(item.role),
                )
                for item in evidence
            ),
        )
    )
    return KnowledgeCreateRequest(
        idempotency_key=command.idempotency_key,
        authenticated_client_id=authenticated_client_id,
        request_digest=digest,
        subject_kind=candidate.subject_kind.value,
        subject_id=candidate.subject_id,
        predicate_code=predicate.predicate_code,
        predicate_version=predicate.predicate_version,
        value_type=predicate.value_type.value,
        cardinality=predicate.cardinality.value,
        temporal_semantics=predicate.temporal_semantics.value,
        qualifier_rule=predicate.qualifier_rule.value,
        allowed_entity_types=frozenset(kind.value for kind in predicate.allowed_entity_types),
        canonical_owner=predicate.canonical_owner.value,
        classification_floor=predicate.classification_floor,
        value_text=candidate.value.value_text,
        value_datetime=candidate.value.value_datetime,
        normalized_value_sha256=candidate.value.sha256,
        qualifier=candidate.qualifier,
        effective_from=candidate.effective_from,
        effective_to=candidate.effective_to,
        assertion_fingerprint=candidate.fingerprint(),
        evidence=evidence,
        domain_owned=domain_owned,
    )


# --- autonomous submit: the admission policy's evidence facts ----------------------


def submit_admission_evidence(
    command: SubmitKnowledgeAssertion,
    *,
    origin_system: KnowledgeOriginSystem,
    unavailable_identities: frozenset[tuple[str, ...]] = frozenset(),
) -> tuple[AdmissionEvidence, ...]:
    """The shape-only evidence facts of one submit, for `decide_direct_admission`.

    External entries take the *command's* source profile (a client can never
    cite another profile's object) and the profile's `origin_system` read by
    the server. Only identity, role and availability survive: the excerpt and
    `retrieved_at` are dropped here, so nothing written in evidence content can
    reach the admission decision (KLP-AC-068/069). `unavailable_identities`
    names the external identities (`(external_object_id, version or "",
    content_hash)`) the server knows to be unavailable.
    """
    facts: list[AdmissionEvidence] = []
    for item in command.evidence:
        kind = KnowledgeEvidenceIdentityKind(str(item["identity_kind"]))
        role = KnowledgeEvidenceRole(str(item["role"]))
        content_hash = str(item["content_hash"])
        if kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT:
            object_id = str(item["external_object_id"])
            raw_version = item.get("external_version_id")
            version = None if raw_version is None else str(raw_version)
            facts.append(
                AdmissionEvidence(
                    identity_kind=kind,
                    role=role,
                    content_hash=content_hash,
                    source_profile_id=command.source_profile_id,
                    origin_system=origin_system,
                    external_object_id=object_id,
                    external_version_id=version,
                    available=(object_id, version or "", content_hash)
                    not in unavailable_identities,
                )
            )
        elif kind is KnowledgeEvidenceIdentityKind.CAPTURE:
            facts.append(
                AdmissionEvidence(
                    identity_kind=kind,
                    role=role,
                    content_hash=content_hash,
                    capture_id=str(item["capture_id"]),
                )
            )
        else:
            facts.append(
                AdmissionEvidence(
                    identity_kind=kind,
                    role=role,
                    content_hash=content_hash,
                    relationship_memory_id=str(item["relationship_memory_id"]),
                )
            )
    return tuple(facts)


# --- cursors ---------------------------------------------------------------------


def encode_knowledge_cursor(row: KnowledgeAssertionRow) -> str:
    """An opaque keyset position after `row`: its creation time and identifier."""
    payload = json.dumps(
        {"a": row.assertion_id, "t": row.created_at.isoformat()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_knowledge_cursor(token: str | None) -> tuple[datetime, str] | None:
    """The position a cursor names, or `invalid_request(cursor)`. No lookup happens."""
    if token is None:
        return None
    decoded: Any = None
    if _CURSOR_ALPHABET.fullmatch(token):
        padded = token + "=" * (-len(token) % 4)
        try:
            decoded = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        except (binascii.Error, UnicodeDecodeError, ValueError):
            decoded = None
    if isinstance(decoded, dict) and set(decoded) == {"a", "t"}:
        assertion_id, instant = decoded["a"], decoded["t"]
        if isinstance(assertion_id, str) and _ASSERTION_ID.fullmatch(assertion_id):
            parsed: datetime | None = None
            if isinstance(instant, str):
                try:
                    parsed = datetime.fromisoformat(instant)
                except ValueError:
                    parsed = None
            if parsed is not None and parsed.tzinfo is not None:
                return parsed, assertion_id
    raise InvalidRequestError(SafeDetail.CURSOR)


# --- views -----------------------------------------------------------------------


def _instant(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def assertion_view(row: KnowledgeAssertionRow) -> dict[str, object]:
    """The public shape of one assertion. Its value and nothing of its evidence."""
    value: str | None = row.value_text if row.value_type == KnowledgeValueType.TEXT.value else None
    if row.value_type == KnowledgeValueType.DATETIME.value:
        value = _instant(row.value_datetime)
    return {
        "assertion_id": row.assertion_id,
        "subject_kind": row.subject_kind,
        "subject_id": row.subject_id,
        "predicate_code": row.predicate_code,
        "predicate_version": row.predicate_version,
        "value_type": row.value_type,
        "value": value,
        "qualifier": None if row.qualifier is None else dict(row.qualifier),
        "effective_from": _instant(row.effective_from),
        "effective_to": _instant(row.effective_to),
        "epistemic_status": row.epistemic_status,
        "classification": row.classification,
        "lifecycle": row.lifecycle,
        "version": row.version,
        "supersedes_assertion_id": row.supersedes_assertion_id,
        "created_at": _instant(row.created_at),
        "updated_at": _instant(row.updated_at),
    }


def page_view(page: KnowledgeAssertionPage) -> dict[str, object]:
    """A page and its `next_cursor` (only when a further row exists)."""
    return {
        "assertions": [assertion_view(row) for row in page.rows],
        "next_cursor": (
            encode_knowledge_cursor(page.rows[-1]) if page.has_more and page.rows else None
        ),
    }


def history_view(history: KnowledgeAssertionHistory) -> dict[str, object]:
    return {
        "assertion": assertion_view(history.assertion),
        "mutations": [
            {
                "mutation_id": mutation.mutation_id,
                "mutation_kind": mutation.mutation_kind,
                "prior_version": mutation.prior_version,
                "new_version": mutation.new_version,
                "created_at": _instant(mutation.created_at),
            }
            for mutation in history.mutations
        ],
        "predecessor_assertion_id": history.predecessor_id,
        "successor_assertion_id": history.successor_id,
    }


def reveal_view(reveal: KnowledgeAssertionReveal) -> dict[str, object]:
    return {
        "assertion": assertion_view(reveal.assertion),
        "origin": {
            "submission_id": reveal.submission_id,
            "submission_origin": reveal.submission_origin,
        },
        "evidence": [
            {
                "evidence_ref_id": item.evidence_ref_id,
                "evidence_role": item.evidence_role,
                "identity_kind": item.identity_kind,
                "capture_id": item.capture_id,
                "relationship_memory_id": item.relationship_memory_id,
                "source_profile_id": item.source_profile_id,
                "external_object_id": item.external_object_id,
                "external_version_id": item.external_version_id,
                "content_hash": item.content_hash,
                "excerpt": item.excerpt,
                "excerpt_sha256": item.excerpt_sha256,
                "content_origin": item.content_origin,
                "source_classification": item.source_classification,
                "availability_state": item.availability_state,
                "availability_revalidation_pending": item.availability_revalidation_pending,
            }
            for item in reveal.evidence
        ],
    }


def submission_view(result: KnowledgeSubmissionResult) -> dict[str, object]:
    """The stored public result plus the read-only `current_lifecycle` (R6 6.3)."""
    return {
        "submission_id": result.submission_id,
        "outcome": result.outcome,
        "reason": result.reason,
        "assertion_id": result.assertion_id,
        "assertion_version": result.assertion_version,
        "mutation_id": result.mutation_id,
        "canonical_owner": result.canonical_owner,
        "current_lifecycle": result.current_lifecycle,
    }
