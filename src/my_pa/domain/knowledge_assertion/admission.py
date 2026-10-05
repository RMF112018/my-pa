"""The server-owned direct-admission policy of autonomous submit (KLP-WP-04).

One pure function decides what an autonomous candidate becomes, from facts the
server gathered itself: the immutable predicate head, the bound source
profile's controls, how the subject resolved, the *shape* of each cited
evidence identity, the cited evidence's availability, and the live fact (if
any) holding the single-current slot. It returns a closed decision whose
reason is a stored `KnowledgeSubmissionReason` and whose `blockers` are the
machine codes that kept a candidate out of direct admission (KLP-AC-024).

**Why the domain package.** The rule is pure and has to be provable FAST, and
the application layer (autonomous submit, slice B2) only gathers the facts and
writes what this decides -- the same split `predicate.py`, `digest.py` and
`provenance.py` already use. Nothing here reads a database or a clock.

**What the policy can never see** (KLP-AC-068/069). `AdmissionEvidence` holds
identity shape, role and availability only: no excerpt, no caller text, no
retrieved_at, no declared classification. An instruction embedded in evidence
text therefore cannot change the predicate, the admission policy, the grants,
the profile, the classification floor or the outcome -- there is no field
through which it could arrive. Likewise no observation timestamp reaches the
decision, so a newer timestamp alone never establishes supersession
(KLP-AC-030).

**Order of the rules** (most restrictive first):

1. a disabled profile refuses `source_profile_inactive` (KLP-AC-090);
2. a predicate whose canonical owner is not the Knowledge plane is
   `DOMAIN_OWNED` -- the routing table (R6 section 13) decides routed vs
   no-intake, never this policy;
3. a profile whose authority ceiling is below the predicate's minimum evidence
   authority refuses `source_authority_insufficient`;
4. a subject that is not one canonical identifier of an allowed kind (name or
   fuzzy resolution, wrong kind or entity type, an absent row, Relationship
   Intelligence not composed) refuses `subject_not_canonical` (KLP-AC-026);
5. a cited Capture root that is archived refuses `capture_archived`;
6. otherwise the candidate is direct-admitted only when *every* precondition
   holds, else it is queued for Review with the predicate's own review
   requirement as the reason. The preconditions: the predicate admits
   autonomously (`authoritative_source`) and is not consequential
   (KLP-AC-025, KLP-AC-098); the profile is direct-admission enabled,
   read-only proven and has the authoritative ceiling (KLP-AC-062); at least
   one `direct` evidence row is external, from the submitting profile, and has
   a stable identity -- an external version id or a SHA-256 content hash
   (KLP-AC-011); no counterevidence is cited; every cited external row is
   available.
7. a direct candidate facing a different live single-current fact supersedes
   it only when the successor's `effective_from` is known, not earlier than
   the predecessor's, not future-dated, and the predecessor has no unresolved
   counterevidence (KLP-AC-031, decision half); otherwise it is queued.

**Independence** (KLP-AC-032, KLP-AC-125). `content_origin` is derived from the
identity shape and the profile's `is_synthetic` (the vocabulary has no
`unknown`/`ai_generated` token), and the independence key from the profile's
origin system plus the native identity -- never from caller text. Evidence is
exactly an external object, a Capture or a Relationship Memory: no evidence
shape can be a Knowledge Assertion or a `knowledge_assertion` Record Event,
and trigger events are never evidence, so neither can ever count.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCanonicalOwner,
    KnowledgeCardinality,
    KnowledgeConsequentialClass,
    KnowledgeContentOrigin,
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeOriginSystem,
    KnowledgeOwnerRefKind,
    KnowledgeReadOnlyProofState,
    KnowledgeReviewRequirement,
    KnowledgeSubmissionOutcome,
    KnowledgeSubmissionReason,
)

__all__ = [
    "OWNER_REF_ROUTES",
    "AdmissionDecision",
    "AdmissionEvidence",
    "AdmissionPath",
    "CurrentFact",
    "DirectAdmissionBlocker",
    "DirectAdmissionFacts",
    "DomainRoute",
    "InvalidAdmissionFactsError",
    "SourceProfileFacts",
    "SubjectResolution",
    "decide_direct_admission",
    "decide_domain_route",
    "derive_content_origin",
    "independence_key",
    "independent_corroboration_keys",
]

_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_AUTHORITY_RANK: Final = {
    KnowledgeEvidenceAuthority.OBSERVED_SOURCE: 0,
    KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE: 1,
}


class InvalidAdmissionFactsError(ValueError):
    """The caller handed the policy facts it must never hand it. Names no value."""


class AdmissionPath(StrEnum):
    """What the server does with a candidate."""

    DIRECT_CREATE = "direct_create"
    DIRECT_SUPERSEDE = "direct_supersede"
    REVIEW = "review"
    REFUSE = "refuse"
    DOMAIN_OWNED = "domain_owned"


class DirectAdmissionBlocker(StrEnum):
    """Machine codes for why a candidate was not direct-admitted (KLP-AC-024)."""

    PREDICATE_NEVER_DIRECT_ADMITS = "predicate_never_direct_admits"
    CONSEQUENTIAL_PREDICATE = "consequential_predicate"
    PROFILE_DIRECT_ADMISSION_DISABLED = "profile_direct_admission_disabled"
    PROFILE_READ_ONLY_UNPROVEN = "profile_read_only_unproven"
    PROFILE_CEILING_NOT_AUTHORITATIVE = "profile_ceiling_not_authoritative"
    NO_DIRECT_EXTERNAL_EVIDENCE = "no_direct_external_evidence"
    EXTERNAL_IDENTITY_UNSTABLE = "external_identity_unstable"
    COUNTEREVIDENCE_CITED = "counterevidence_cited"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    CURRENT_FACT_DIFFERS = "current_fact_differs"
    SUCCESSOR_EFFECTIVE_FROM_UNKNOWN = "successor_effective_from_unknown"
    SUCCESSOR_EFFECTIVE_FROM_REGRESSES = "successor_effective_from_regresses"
    SUCCESSOR_FUTURE_DATED = "successor_future_dated"
    PREDECESSOR_COUNTEREVIDENCE_UNRESOLVED = "predecessor_counterevidence_unresolved"


class SubjectResolution(StrEnum):
    """How the server resolved the candidate's subject. Only `canonical` admits."""

    CANONICAL = "canonical"
    UNRESOLVED = "unresolved"
    NAME_OR_FUZZY_ONLY = "name_or_fuzzy_only"
    KIND_NOT_ALLOWED = "kind_not_allowed"
    ENTITY_TYPE_NOT_ALLOWED = "entity_type_not_allowed"
    PLANE_NOT_COMPOSED = "plane_not_composed"


@dataclass(frozen=True, slots=True)
class SourceProfileFacts:
    """The bound source profile's controls, read by the server at C4a."""

    source_profile_id: str
    origin_system: KnowledgeOriginSystem
    authority_ceiling: KnowledgeEvidenceAuthority
    direct_admission_enabled: bool
    read_only_proof_state: KnowledgeReadOnlyProofState
    is_synthetic: bool
    disabled: bool


@dataclass(frozen=True, slots=True)
class AdmissionEvidence:
    """One cited evidence identity's *shape*, role and availability.

    Deliberately no excerpt, text, retrieved_at or declared class: nothing a
    caller writes in evidence content can reach the decision.
    """

    identity_kind: KnowledgeEvidenceIdentityKind
    role: KnowledgeEvidenceRole
    content_hash: str
    source_profile_id: str | None = None
    origin_system: KnowledgeOriginSystem | None = None
    external_object_id: str | None = None
    external_version_id: str | None = None
    #: The cited Capture's or Relationship Memory's identifier (product shapes).
    product_record_id: str | None = None
    available: bool = True

    @property
    def native_identity(self) -> str:
        if self.identity_kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT:
            return str(self.external_object_id)
        return str(self.product_record_id)

    @property
    def is_stable(self) -> bool:
        """An external version id, or a SHA-256 content hash (KLP-AC-011)."""
        version = self.external_version_id
        if version is not None and version.strip():
            return True
        return bool(_SHA256_HEX.fullmatch(self.content_hash))


@dataclass(frozen=True, slots=True)
class CurrentFact:
    """The live assertion holding the single-current slot with a different value."""

    assertion_id: str
    effective_from: datetime | None
    unresolved_counterevidence: bool


@dataclass(frozen=True, slots=True)
class DirectAdmissionFacts:
    """Everything the policy decides from. All server-gathered."""

    predicate: KnowledgePredicate
    profile: SourceProfileFacts
    subject: SubjectResolution
    evidence: tuple[AdmissionEvidence, ...]
    candidate_effective_from: datetime | None
    now: datetime
    current: CurrentFact | None = None
    capture_archived: bool = False


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """The closed decision. `reason` is `None` only for `DOMAIN_OWNED`."""

    path: AdmissionPath
    reason: KnowledgeSubmissionReason | None
    blockers: tuple[DirectAdmissionBlocker, ...] = field(default=())
    supersedes_assertion_id: str | None = None

    @property
    def outcome(self) -> KnowledgeSubmissionOutcome | None:
        """The stored outcome this decision completes as (`None`: routing decides)."""
        return {
            AdmissionPath.DIRECT_CREATE: KnowledgeSubmissionOutcome.DIRECT_CREATED,
            AdmissionPath.DIRECT_SUPERSEDE: KnowledgeSubmissionOutcome.DIRECT_SUPERSEDED,
            AdmissionPath.REVIEW: KnowledgeSubmissionOutcome.REVIEW_QUEUED,
            AdmissionPath.REFUSE: KnowledgeSubmissionOutcome.REFUSED,
            AdmissionPath.DOMAIN_OWNED: None,
        }[self.path]


def _refuse(reason: KnowledgeSubmissionReason) -> AdmissionDecision:
    return AdmissionDecision(path=AdmissionPath.REFUSE, reason=reason)


def _direct_blockers(facts: DirectAdmissionFacts) -> list[DirectAdmissionBlocker]:
    predicate, profile = facts.predicate, facts.profile
    blockers: list[DirectAdmissionBlocker] = []
    if predicate.autonomous_admission_policy is not (
        KnowledgeAutonomousAdmissionPolicy.AUTHORITATIVE_SOURCE
    ):
        blockers.append(DirectAdmissionBlocker.PREDICATE_NEVER_DIRECT_ADMITS)
    if predicate.consequential_class is not KnowledgeConsequentialClass.NONE:
        blockers.append(DirectAdmissionBlocker.CONSEQUENTIAL_PREDICATE)
    if not profile.direct_admission_enabled:
        blockers.append(DirectAdmissionBlocker.PROFILE_DIRECT_ADMISSION_DISABLED)
    if profile.read_only_proof_state is not KnowledgeReadOnlyProofState.PROVEN:
        blockers.append(DirectAdmissionBlocker.PROFILE_READ_ONLY_UNPROVEN)
    if profile.authority_ceiling is not KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE:
        blockers.append(DirectAdmissionBlocker.PROFILE_CEILING_NOT_AUTHORITATIVE)
    direct_external = [
        item
        for item in facts.evidence
        if item.role is KnowledgeEvidenceRole.DIRECT
        and item.identity_kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT
        and item.source_profile_id == profile.source_profile_id
    ]
    if not direct_external:
        blockers.append(DirectAdmissionBlocker.NO_DIRECT_EXTERNAL_EVIDENCE)
    elif not any(item.is_stable for item in direct_external):
        blockers.append(DirectAdmissionBlocker.EXTERNAL_IDENTITY_UNSTABLE)
    if any(item.role is KnowledgeEvidenceRole.COUNTEREVIDENCE for item in facts.evidence):
        blockers.append(DirectAdmissionBlocker.COUNTEREVIDENCE_CITED)
    if any(not item.available for item in facts.evidence):
        blockers.append(DirectAdmissionBlocker.EVIDENCE_UNAVAILABLE)
    return blockers


def _supersession_blockers(
    facts: DirectAdmissionFacts, current: CurrentFact
) -> list[DirectAdmissionBlocker]:
    blockers = [DirectAdmissionBlocker.CURRENT_FACT_DIFFERS]
    successor = facts.candidate_effective_from
    predecessor = current.effective_from
    if successor is None or predecessor is None:
        blockers.append(DirectAdmissionBlocker.SUCCESSOR_EFFECTIVE_FROM_UNKNOWN)
    else:
        if successor < predecessor:
            blockers.append(DirectAdmissionBlocker.SUCCESSOR_EFFECTIVE_FROM_REGRESSES)
        if successor > facts.now:
            blockers.append(DirectAdmissionBlocker.SUCCESSOR_FUTURE_DATED)
    if current.unresolved_counterevidence:
        blockers.append(DirectAdmissionBlocker.PREDECESSOR_COUNTEREVIDENCE_UNRESOLVED)
    return blockers


def decide_direct_admission(facts: DirectAdmissionFacts) -> AdmissionDecision:
    """Decide one autonomous candidate. Pure; the order is the module docstring's."""
    predicate, profile = facts.predicate, facts.profile
    if not predicate.is_open_for_intake:
        raise InvalidAdmissionFactsError("a retired predicate head is refused before admission")
    if facts.current is not None and predicate.cardinality is not (
        KnowledgeCardinality.SINGLE_CURRENT
    ):
        raise InvalidAdmissionFactsError("only a single_current predicate has a current slot")
    if profile.disabled:
        return _refuse(KnowledgeSubmissionReason.SOURCE_PROFILE_INACTIVE)
    if predicate.canonical_owner is not KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION:
        return AdmissionDecision(path=AdmissionPath.DOMAIN_OWNED, reason=None)
    if (
        _AUTHORITY_RANK[profile.authority_ceiling]
        < _AUTHORITY_RANK[predicate.minimum_evidence_authority]
    ):
        return _refuse(KnowledgeSubmissionReason.SOURCE_AUTHORITY_INSUFFICIENT)
    if facts.subject is not SubjectResolution.CANONICAL:
        return _refuse(KnowledgeSubmissionReason.SUBJECT_NOT_CANONICAL)
    if facts.capture_archived:
        return _refuse(KnowledgeSubmissionReason.CAPTURE_ARCHIVED)
    review = (
        KnowledgeSubmissionReason.REQUIRES_OPERATOR
        if predicate.review_requirement is KnowledgeReviewRequirement.REQUIRES_OPERATOR
        else KnowledgeSubmissionReason.REQUIRES_REVIEW
    )
    blockers = _direct_blockers(facts)
    if blockers:
        return AdmissionDecision(path=AdmissionPath.REVIEW, reason=review, blockers=tuple(blockers))
    if facts.current is None:
        return AdmissionDecision(
            path=AdmissionPath.DIRECT_CREATE, reason=KnowledgeSubmissionReason.CREATED
        )
    held = _supersession_blockers(facts, facts.current)
    if len(held) > 1:
        return AdmissionDecision(path=AdmissionPath.REVIEW, reason=review, blockers=tuple(held))
    return AdmissionDecision(
        path=AdmissionPath.DIRECT_SUPERSEDE,
        reason=KnowledgeSubmissionReason.SUPERSEDED,
        supersedes_assertion_id=facts.current.assertion_id,
    )


# --- content origin and independence --------------------------------------------


def derive_content_origin(
    identity_kind: KnowledgeEvidenceIdentityKind, *, profile_is_synthetic: bool | None
) -> KnowledgeContentOrigin:
    """The stored `content_origin`: from the identity shape and the profile only."""
    if identity_kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT:
        if profile_is_synthetic is None:
            raise InvalidAdmissionFactsError("external evidence needs its profile's synthetic flag")
        return (
            KnowledgeContentOrigin.SYNTHETIC_SOURCE
            if profile_is_synthetic
            else KnowledgeContentOrigin.EXTERNAL_SOURCE
        )
    if identity_kind is KnowledgeEvidenceIdentityKind.CAPTURE:
        return KnowledgeContentOrigin.CAPTURE
    return KnowledgeContentOrigin.RELATIONSHIP_MEMORY


def independence_key(evidence: AdmissionEvidence) -> str:
    """sha256 over (identity kind, origin system, native identity). Server-derived.

    The external key uses the profile's *origin system*, not the profile id:
    the same external object seen through two overlapping profiles of one
    origin system is one source, not two (most restrictive reading). Version,
    content hash, role and every caller-written field are excluded.
    """
    if evidence.identity_kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT:
        if evidence.origin_system is None or evidence.external_object_id is None:
            raise InvalidAdmissionFactsError("external evidence needs its origin and object")
        parts = [evidence.identity_kind.value, evidence.origin_system.value]
    else:
        parts = [evidence.identity_kind.value, ""]
    parts.append(evidence.native_identity)
    encoded = json.dumps(parts, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def independent_corroboration_keys(evidence: Iterable[AdmissionEvidence]) -> frozenset[str]:
    """The distinct independence keys of the evidence that corroborates.

    Counterevidence never corroborates. Only cited evidence is read: trigger
    events (including `knowledge_assertion` Record Events) are not evidence and
    have no way into this function.
    """
    return frozenset(
        independence_key(item)
        for item in evidence
        if item.role is not KnowledgeEvidenceRole.COUNTEREVIDENCE
    )


# --- DOMAIN_OWNED routes (R6 sections 8.5 and 13) --------------------------------------

#: `project.critical_date`'s owner-ref kinds and the canonical owner each routes to.
OWNER_REF_ROUTES: Final = {
    KnowledgeOwnerRefKind.TASK: KnowledgeCanonicalOwner.TASKS,
    KnowledgeOwnerRefKind.COMMITMENT: KnowledgeCanonicalOwner.COMMITMENTS,
    KnowledgeOwnerRefKind.CONSTRAINT: KnowledgeCanonicalOwner.CONSTRAINTS,
    KnowledgeOwnerRefKind.MEETING: KnowledgeCanonicalOwner.MEETINGS,
}
_CRITICAL_DATE: Final = "project.critical_date"


@dataclass(frozen=True, slots=True)
class DomainRoute:
    """A DOMAIN_OWNED completion decided at C2 from the immutable predicate head."""

    outcome: KnowledgeSubmissionOutcome
    reason: KnowledgeSubmissionReason
    canonical_owner: KnowledgeCanonicalOwner | None
    routed_record_id: str | None = None


def decide_domain_route(
    predicate: KnowledgePredicate,
    *,
    owner_ref_kind: KnowledgeOwnerRefKind | None,
    owner_ref_id: str | None,
    owner_ref_resolves: bool,
) -> DomainRoute | None:
    """The DOMAIN_OWNED route of one candidate, or `None` (the Knowledge plane's).

    Pure: the caller reads whether the owner ref resolves (a Principal-scoped
    existence read at C2) and nothing else.

    * `project.critical_date` with an owner ref: resolving -> `domain_owned_routed`
      to that owner with `routed_record_id` = the ref; unresolvable -> refused
      `owner_ref_invalid`; no ref -> the Knowledge plane (Review). No inference.
    * An owner ref on any other predicate -> refused `owner_ref_invalid`
      (plan-silent; most restrictive: no other route reads one).
    * A predicate owned outside the Knowledge plane -> `domain_owned_no_intake`
      naming that owner (`project.decision` -> `continuity_decision`, KLP-AC-097).
      `relationship_memory` (`entity.communication_preference`) is no-intake in
      this build: its proposal writer cites a capture span, an entity
      observation or a knowledge record, and no Knowledge citation names one,
      so no evidence is transferable (KLP-WP-04 deviation).
    """
    if owner_ref_kind is not None:
        if predicate.predicate_code != _CRITICAL_DATE or not owner_ref_resolves:
            return DomainRoute(
                outcome=KnowledgeSubmissionOutcome.REFUSED,
                reason=KnowledgeSubmissionReason.OWNER_REF_INVALID,
                canonical_owner=None,
            )
        return DomainRoute(
            outcome=KnowledgeSubmissionOutcome.DOMAIN_OWNED_ROUTED,
            reason=KnowledgeSubmissionReason.CANONICAL_OWNER,
            canonical_owner=OWNER_REF_ROUTES[owner_ref_kind],
            routed_record_id=owner_ref_id,
        )
    if predicate.canonical_owner is not KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION:
        return DomainRoute(
            outcome=KnowledgeSubmissionOutcome.DOMAIN_OWNED_NO_INTAKE,
            reason=KnowledgeSubmissionReason.CANONICAL_OWNER_NO_INTAKE,
            canonical_owner=predicate.canonical_owner,
        )
    return None
