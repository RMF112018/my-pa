"""Knowledge causal provenance model as pure data (KLP-WP-01; R5 CORR-006, R6 section 9).

Consumed by WP-04 (submit causality) and WP-05 (cross-run provenance read);
nothing here touches persistence.

**One bounded lineage model.**

* No Knowledge-parent trigger -> a new root (root = own submission, depth 0).
  Non-Knowledge trigger events are visible trigger evidence but carry no
  Knowledge lineage, and a Knowledge trigger whose mutation has no submission
  (server maintenance) contributes no root either.
* Exactly one distinct Knowledge root among the parents -> inherit it, depth =
  1 + max(parent depth).
* More than one distinct root -> refuse `causal_root_ambiguous`.
* Depth above `MAX_CAUSAL_DEPTH` (4; the only ceiling) -> refuse
  `causal_depth_exceeded`.
* A repeated (authenticated_client_id, subject_kind, subject_id, predicate_code)
  anywhere in the ancestor lineage -> refuse `causal_repeat`, whatever the
  external_run_id.
* Explicit create is always a root. Review promotion inherits the proposal's
  origin submission, so `review.decide` never resets depth.
* Independently of citation, an autonomous submit is refused
  `causal_rate_exceeded` once the same client already has
  `CAUSAL_RATE_LIMIT` admitted submissions on the same subject key within the
  same external run (a soft, approximate loop limiter, not an integrity rule).

**Record Event mapping (frozen).** Every Knowledge Assertion Record Event names
its `kamut_` mutation as `source_receipt_id`; mutation -> submission is the
cross-run join. Event kind and changed-field tokens follow the mutation kind;
actor class and authority follow who caused the write, using only the existing
closed `RecordEventActorClass` / `RecordEventAuthority` members.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeMutationKind,
    KnowledgeSubmissionOutcome,
    KnowledgeSubmissionReason,
)
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventAuthority,
    RecordEventKind,
)

__all__ = [
    "CAUSAL_RATE_COUNTED_OUTCOMES",
    "CAUSAL_RATE_LIMIT",
    "KNOWLEDGE_EVENT_ACTOR_CLASSES",
    "KNOWLEDGE_EVENT_AUTHORITIES",
    "KNOWLEDGE_MUTATION_EVENTS",
    "MAX_CAUSAL_DEPTH",
    "CausalKey",
    "CausalParent",
    "CausalPosition",
    "CausalRefusal",
    "KnowledgeEventOrigin",
    "MutationEvent",
    "resolve_causal_position",
]

#: The one causal depth ceiling (CHECK `causal_depth BETWEEN 0 AND 4`).
MAX_CAUSAL_DEPTH: Final = 4
#: Admitted submissions per (client, subject key, external run) before
#: `causal_rate_exceeded` (R6 section 9.3).
CAUSAL_RATE_LIMIT: Final = 16
CAUSAL_RATE_COUNTED_OUTCOMES: Final[frozenset[KnowledgeSubmissionOutcome]] = frozenset(
    {
        KnowledgeSubmissionOutcome.DIRECT_CREATED,
        KnowledgeSubmissionOutcome.DIRECT_SUPERSEDED,
        KnowledgeSubmissionOutcome.DUPLICATE_ENRICHED,
        KnowledgeSubmissionOutcome.REVIEW_QUEUED,
    }
)


@dataclass(frozen=True, slots=True)
class CausalKey:
    """The lineage repeat key of one submission."""

    authenticated_client_id: str | None
    subject_kind: str
    subject_id: str
    predicate_code: str


@dataclass(frozen=True, slots=True)
class CausalParent:
    """The causal snapshot of one Knowledge trigger's parent submission."""

    root_submission_id: str
    depth: int


@dataclass(frozen=True, slots=True)
class CausalPosition:
    """An admitted causal position: root and depth."""

    root_submission_id: str
    depth: int


@dataclass(frozen=True, slots=True)
class CausalRefusal:
    """A causal refusal; such a submission is born completed with NULL causal fields."""

    reason: KnowledgeSubmissionReason


def resolve_causal_position(
    *,
    own_submission_id: str,
    own_key: CausalKey,
    parents: Iterable[CausalParent],
    ancestor_keys: Iterable[CausalKey],
) -> CausalPosition | CausalRefusal:
    """Apply the bounded lineage rule to one submission.

    `parents` are the snapshots of Knowledge triggers that resolve to a
    submission; non-Knowledge triggers and maintenance mutations are simply not
    passed. `ancestor_keys` are the repeat keys of every ancestor in the lineage.
    """
    snapshots = list(parents)
    if own_key in set(ancestor_keys):
        return CausalRefusal(KnowledgeSubmissionReason.CAUSAL_REPEAT)
    if not snapshots:
        return CausalPosition(root_submission_id=own_submission_id, depth=0)
    roots = {parent.root_submission_id for parent in snapshots}
    if len(roots) > 1:
        return CausalRefusal(KnowledgeSubmissionReason.CAUSAL_ROOT_AMBIGUOUS)
    depth = 1 + max(parent.depth for parent in snapshots)
    if depth > MAX_CAUSAL_DEPTH:
        return CausalRefusal(KnowledgeSubmissionReason.CAUSAL_DEPTH_EXCEEDED)
    return CausalPosition(root_submission_id=roots.pop(), depth=depth)


class KnowledgeEventOrigin(StrEnum):
    """Who caused a Knowledge write, for the Record Event actor/authority map.

    Python-only: not a stored column and not a closed DB vocabulary.
    """

    AUTONOMOUS_SUBMIT = "autonomous_submit"
    EXPLICIT_CREATE = "explicit_create"
    REVIEW_PROMOTION = "review_promotion"
    SERVER_MAINTENANCE = "server_maintenance"


#: Actor class per origin, from the existing closed `RecordEventActorClass`.
KNOWLEDGE_EVENT_ACTOR_CLASSES: Final[Mapping[KnowledgeEventOrigin, RecordEventActorClass]] = (
    MappingProxyType(
        {
            KnowledgeEventOrigin.AUTONOMOUS_SUBMIT: RecordEventActorClass.ASSISTANT,
            KnowledgeEventOrigin.EXPLICIT_CREATE: RecordEventActorClass.PRINCIPAL,
            KnowledgeEventOrigin.REVIEW_PROMOTION: RecordEventActorClass.REVIEW_PROMOTION,
            KnowledgeEventOrigin.SERVER_MAINTENANCE: RecordEventActorClass.SYSTEM,
        }
    )
)
#: Authority per origin, from the existing closed `RecordEventAuthority`.
KNOWLEDGE_EVENT_AUTHORITIES: Final[Mapping[KnowledgeEventOrigin, RecordEventAuthority]] = (
    MappingProxyType(
        {
            KnowledgeEventOrigin.AUTONOMOUS_SUBMIT: RecordEventAuthority.SOURCE_BACKED_ASSERTION,
            KnowledgeEventOrigin.EXPLICIT_CREATE: RecordEventAuthority.USER_CONFIRMED_ASSERTION,
            KnowledgeEventOrigin.REVIEW_PROMOTION: RecordEventAuthority.REVIEW_ACCEPTED,
            KnowledgeEventOrigin.SERVER_MAINTENANCE: RecordEventAuthority.SYSTEM_DETERMINISTIC,
        }
    )
)


@dataclass(frozen=True, slots=True)
class MutationEvent:
    """The Record Event kind and sorted changed-field tokens of one mutation kind."""

    kind: RecordEventKind
    changed_fields: tuple[str, ...]


_CREATED: Final = MutationEvent(
    RecordEventKind.CREATED, ("classification", "epistemic_status", "lifecycle", "value")
)
_LIFECYCLE: Final = MutationEvent(RecordEventKind.STATE_CHANGED, ("lifecycle",))

#: Total over `KnowledgeMutationKind`.
KNOWLEDGE_MUTATION_EVENTS: Final[Mapping[KnowledgeMutationKind, MutationEvent]] = MappingProxyType(
    {
        KnowledgeMutationKind.CREATE: _CREATED,
        KnowledgeMutationKind.REVIEW_ACCEPT: _CREATED,
        KnowledgeMutationKind.REVIEW_CORRECT: _CREATED,
        KnowledgeMutationKind.SUPERSEDE_SUCCESSOR: _CREATED,
        KnowledgeMutationKind.SUPERSEDE_PREDECESSOR: _LIFECYCLE,
        KnowledgeMutationKind.EVIDENCE_ENRICH: MutationEvent(
            RecordEventKind.UPDATED, ("evidence",)
        ),
        KnowledgeMutationKind.CLASSIFY: MutationEvent(
            RecordEventKind.STATE_CHANGED, ("classification",)
        ),
        KnowledgeMutationKind.REVALIDATION_REQUIRED: _LIFECYCLE,
        KnowledgeMutationKind.REVALIDATION_CLEARED: _LIFECYCLE,
        KnowledgeMutationKind.ARCHIVE: _LIFECYCLE,
    }
)
