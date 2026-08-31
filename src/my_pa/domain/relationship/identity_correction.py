"""What a governed identity correction binds, does, and leaves behind.

Three records, and the separation between them is the whole of `WP-RI-06`'s
safety argument.

**A preview is a binding, not a report.** Operator prompt section 19 requires
`entities.merge.preview` to persist what it looked at: the exact entities, the
exact versions it read them at, and a digest of both. That is why the preview is
a durable record rather than a computed response — an apply that arrived with
"the same" identities but a different set of versions would otherwise be
indistinguishable from a replay of the preview an operator actually read. The
preview is what makes "you approved *this*" checkable.

**An operation is one act, and it is idempotent by its key and not by its
preview.** Section 23 states the rule this record is shaped by: the preview
token is *not* the mutation idempotency key. They answer different questions. The
preview digest answers "is the world still what the operator was shown"; the
idempotency key answers "have I already performed this request". A design that
collapsed them would make a retry after a concurrent change either a silent
second merge or an un-retryable failure, depending on which meaning won.

**An effect is the evidence a later split has to work from.** Section 22 requires
the ledger to be "sufficiently complete and deterministic for `WP-07` to invert a
governed merge later", and says in the same breath: do not fake invertibility by
recording only redirects. So every effect carries the row's state on both sides
of the change, both states are required rather than optional, and the vocabulary
below is organised by *what undoing each effect would take* rather than by which
table the row lives in. `WP-07` is not implemented here and nothing in this
module performs a merge; what is implemented is the record that makes performing
one recoverable.

**No raw personal narrative text enters the preview or the operation.** Sections
19 and 28 draw that line, and it is drawn here in the shape of the records: the
preview and the operation carry identifiers, versions, digests and one bounded
reason, and there is no column on either that a statement, a name or a source
span could go in. The *effect* ledger is the exception the same sections admit —
before/after state is canonical recovery evidence — and it is bounded and
classified rather than open: both states are `repr=False` on the argument
`EntityMutationEvent` records for its own pair, and the writers on this plane
put identifiers, closed vocabulary members and versions in them and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.governance import ENTITY_CHANGE_REASON_LIMIT, ActorClass
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "IDENTITY_PREVIEW_LIFETIME",
    "MAX_MERGED_AWAY_ENTITIES",
    "AmbiguityDisposition",
    "AmbiguityReason",
    "IdentityConflict",
    "IdentityConflictKind",
    "IdentityEffect",
    "IdentityEffectDraft",
    "IdentityEffectFamily",
    "IdentityEffectKind",
    "IdentityOperation",
    "IdentityOperationState",
    "IdentityOperationType",
    "IdentityPreview",
    "ambiguity_digest_for",
    "blocks_merge",
    "conflict_digest_for",
    "current_record_id",
    "dispositions_for",
    "effects_digest_for",
    "plan_digest_for",
    "preview_digest_for",
    "sequence_effects",
    "sequence_inverse_effects",
    "state_digest",
]

#: How long a persisted merge preview stays usable, fixed by operator prompt
#: section 19 and by `MYPA-RI-COMP-04`'s own line for `entity_identity_previews`.
#:
#: **Fixed rather than configured, and named rather than spelled at each site.**
#: A preview is a statement that a set of entities held a set of versions at a
#: moment, and the operator is being asked to authorise a mutation against that
#: statement. Every minute it stays valid is a minute in which the statement can
#: become false without anything noticing -- the version check at apply is what
#: catches that, and the expiry is what bounds how much the operator is being
#: asked to trust it for. Fifteen minutes is long enough to read a preview that
#: enumerates ten identities and every record family they touch, and short
#: enough that an approval left open over lunch is refused rather than honoured.
#:
#: A configurable lifetime would make the bound a deployment property, and the
#: first thing a caller under time pressure would do is raise it. `IdentityPreview`
#: therefore derives `expires_at` from `created_at` and refuses any other value,
#: so a writer cannot extend one preview by writing a later timestamp.
IDENTITY_PREVIEW_LIFETIME: Final = timedelta(minutes=15)

#: How many entities one merge may merge away, from operator prompt section 19's
#: "1..10 merged-away Entity IDs". Bounded because every affected record family is
#: enumerated per merged-away entity, and an unbounded set makes the preview's own
#: cost unbounded -- which is how a preview stops being something an operator can
#: read before deciding.
MAX_MERGED_AWAY_ENTITIES: Final = 10

#: The shape a SHA-256 digest takes, restated here because the CHECKs on the three
#: `entity_identity_*` tables say the same thing in SQL and the two have to refuse
#: the same values. The same restatement `governance` makes for `request_digest`.
_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")


class IdentityOperationType(StrEnum):
    """Which governed identity correction one preview and one operation name.

    **One member, and the absence of the second is deliberate.** The composed
    target names `merge` and `split`; operator prompt section 22 says in the same
    document that `WP-06` does not implement split. Declaring `split` here would
    put a value in a closed set that nothing issues and that no code path can
    produce -- which is exactly what `D-RI-04` refused when it declined to
    declare identifier prefixes for records no work package had yet created: a
    closed vocabulary is a promise about what can be stored, and promising one
    for a record nothing writes is a promise about nothing.

    What it costs to add later is one restatement of the CHECK on
    `entity_identity_previews.operation_type` and
    `entity_identity_operations.operation_type` -- the same cost `823e23b6cc63`
    paid to widen the stored audit vocabulary, and the ordinary price of widening
    a closed set. `WP-07` pays it with the code that writes the value.
    """

    MERGE = "merge"
    SPLIT = "split"


class IdentityOperationState(StrEnum):
    """Where one identity operation stands.

    Three states, and the first one exists because a crash has to be legible.
    Apply is atomic (section 21), so a rolled-back merge leaves no effects and no
    canonical change -- but the operation row is written *before* the work and is
    the row an idempotent retry finds, so without `IN_PROGRESS` a process that
    died mid-apply would leave a row indistinguishable from a completed merge and
    a retry would answer "already done" about a merge that never happened.

    `FAILED` is a decided outcome rather than a stuck one: the request was
    admitted, the work was attempted, and it did not complete. A refusal *before*
    admission -- an expired preview, a mismatched digest, a stale version -- writes
    no operation row at all, because nothing was attempted and a ledger of
    requests that were never performed is a different record from this one.
    """

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IdentityConflictKind(StrEnum):
    """Why one record stops a merge, or requires the operator to decide it.

    Three kinds, each traceable to one sentence of the frozen contract:

    * ACTIVE_IDENTIFIER_CONFLICT -- section 21's "conflicting active identifier
      blocks merge". Two entities hold the same identity in the same namespace
      and both bindings are current, so reparenting either would make one address
      the current identity of one entity twice;
    * UNSUPPORTED_FAMILY -- section 20's requirement that a materially affected
      family which "cannot yet be safely transformed with reversible lineage"
      surface an explicit blocker and be refused at apply. This is the honest name
      for any future family that is materially affected but lacks reversible
      lineage. Relationship Memory no longer occupies this boundary: governed
      merge/split records its mutable bindings while preserving immutable origin;
    * AMBIGUOUS_DISPOSITION -- a record the merge could transform in more than one
      defensible way, which section 21 requires the operator to choose between
      before apply.

    Whether a kind blocks is derived rather than stored, on the same argument
    `requirement_for` makes about a proposal's review requirement: a writer that
    could declare its own conflict non-blocking would declare every conflict
    non-blocking.
    """

    ACTIVE_IDENTIFIER_CONFLICT = "active_identifier_conflict"
    UNSUPPORTED_FAMILY = "unsupported_family"
    AMBIGUOUS_DISPOSITION = "ambiguous_disposition"
    #: RI-ENT-WP-06b's addition, for the one hazard none of the other three
    #: kinds names. `entity_organization_profiles.entity_id` is *both* the
    #: table's primary key and its foreign key to `entities` -- an
    #: organization entity has at most one profile row, by construction, and
    #: not merely by convention. When the survivor and a merged-away entity
    #: each hold one, reparenting the merged-away row is a primary-key
    #: collision the database itself would refuse, and coalescing it has no
    #: mechanism to fold into: unlike `ALIAS`/`IDENTIFIER`/`ASSIGNMENT`/
    #: `RELATIONSHIP`, this table carries no `state` and no
    #: `superseded_by_*` column for a losing row to retire into (see
    #: `EntityOrganizationProfile`'s docstring -- "there is nothing here for
    #: `state`/`effective_from`/`superseded_by_*` to mean"). So unlike
    #: `ALIAS`'s active/former conflict, this is not a question with two
    #: defensible answers for an operator to choose between: the schema
    #: admits neither reading, which is exactly the reasoning
    #: `application.identity_correction`'s module docstring already gives for
    #: why an `IDENTIFIER` conflict blocks outright rather than asking. This
    #: kind is deliberately not named after that family, because the same
    #: shape of hazard -- a record family whose row identity is unique per
    #: entity by construction, with no successor column to retire a losing
    #: row into -- could recur for a future one-row-per-entity family, and a
    #: name scoped to organization profiles specifically would have to be
    #: widened rather than reused the day it does.
    SINGLETON_RECORD_CONFLICT = "singleton_record_conflict"


#: Which conflict kinds refuse a merge outright, as against those the operator
#: resolves by choosing. A mapping rather than a field, for the reason
#: `_REQUIREMENT_BY_KIND` is a mapping.
_BLOCKS_BY_KIND: dict[IdentityConflictKind, bool] = {
    IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT: True,
    IdentityConflictKind.UNSUPPORTED_FAMILY: True,
    IdentityConflictKind.AMBIGUOUS_DISPOSITION: False,
    IdentityConflictKind.SINGLETON_RECORD_CONFLICT: True,
}


def blocks_merge(kind: IdentityConflictKind) -> bool:
    """Whether a conflict of `kind` refuses the merge rather than awaiting a choice."""
    return _BLOCKS_BY_KIND[kind]


class IdentityEffectFamily(StrEnum):
    """Which record family one effect is about.

    Deliberately **not** `MutationRecordFamily`, and the difference is the point
    rather than an oversight. That vocabulary is closed at the six families the
    entity plane holds as canonical fact and excludes proposals on the argument
    that "a mutation ledger that also recorded proposals would record the asking
    as if it were the doing". A merge genuinely does something to a proposal: an
    identity change invalidates the pending requests that named the identity, and
    an inversion has to put them back. Recording that in the mutation ledger's
    vocabulary would break its rule; leaving it unrecorded would leave the effect
    ledger unable to invert what the merge did.

    `DERIVED_CONTEXT` is the one member that names something the merge did not
    author. A prepared context package is stale after an identity change, and
    section 21 requires derived state to become stale "where current
    infrastructure supports invalidation". It is recorded here because a split
    has to re-mark exactly the packages a merge marked, and no other record says
    which those were.

    **RI-ENT-WP-06b adds six members** for the Entity-bound record families
    RI-ENT-WP-02 through RI-ENT-WP-05 introduced after this vocabulary was
    first closed: `NAME`, `ORGANIZATION_PROFILE`, `ADDRESS`,
    `COMMUNICATION_METHOD`, `PROJECT_PARTICIPATION`, and
    `PERSON_ORGANIZATION_AFFILIATION`. Each of those five migrations' own
    domain-class docstrings (`EntityName`, `EntityOrganizationProfile`,
    `EntityAddress`, `EntityCommunicationMethod`,
    `EntityProjectParticipation`, `PersonOrganizationAffiliation` in
    `my_pa.domain.relationship.entity`) named this exact wiring as deferred
    to RI-ENT-WP-06; this is that wiring landing. `ENTITY_ROLE_TYPE` and
    `ENTITY_DISCIPLINE_TYPE` are deliberately **not** members here: both
    tables are global, Principal-independent lookup vocabularies with no
    `entity_id` column of any kind, so a merge has no row in either to
    reparent, discover ambiguity for, or invert -- see the campaign
    document's "Merge/split disposition" section for the full, evidenced
    statement of that exclusion.
    """

    ENTITY = "entity"
    IDENTIFIER = "identifier"
    ALIAS = "alias"
    ASSIGNMENT = "assignment"
    RELATIONSHIP = "relationship"
    NAME = "name"
    ORGANIZATION_PROFILE = "organization_profile"
    ADDRESS = "address"
    COMMUNICATION_METHOD = "communication_method"
    PROJECT_PARTICIPATION = "project_participation"
    PERSON_ORGANIZATION_AFFILIATION = "person_organization_affiliation"
    OBSERVATION = "observation"
    PROPOSAL = "proposal"
    REVIEW_CASE = "review_case"
    RELATIONSHIP_MEMORY = "relationship_memory"
    MEMORY_PROPOSAL = "memory_proposal"
    MEMORY_CONTEXT_LINK = "memory_context_link"
    DERIVED_CONTEXT = "derived_context"


class AmbiguityReason(StrEnum):
    """Why a split cannot prove, from the merge ledger alone, where one record belongs.

    **Separate from what the operator decides about it.** A reason is the
    server's finding and a disposition is the operator's answer, and collapsing
    them would let a caller assert the finding: "assign it to this entity
    because it was created after the merge" is two claims, and only the second
    is theirs to make.

    Closed at five members, and the same five the server admits on
    `a_preview_ambiguity_reason_is_known`. `POST_MERGE_MODIFIED` and
    `POST_MERGE_CREATED` are the two this work package discovers -- the recorded
    `after_state` no longer describes the row, and a row bound to the survivor
    that the merge's ledger never mentions. The other three name findings a
    later analysis can raise without this vocabulary having to change under it.
    """

    #: The row still exists and the merge's recorded `after_state` no longer
    #: describes it, so restoring the recorded `before_state` would discard a
    #: change nobody in this operation authored.
    POST_MERGE_MODIFIED = "post_merge_modified"
    #: The row binds to the survivor and appears in no effect the merge
    #: recorded, so the merge ledger carries no lineage saying which of the
    #: participating identities it belongs to.
    POST_MERGE_CREATED = "post_merge_created"
    #: Two lineages disagree about the row's owner.
    CONFLICTING_LINEAGE = "conflicting_lineage"
    #: The row is evidence more than one participant genuinely shares.
    SHARED_EVIDENCE = "shared_evidence"
    #: Ownership cannot be established from any recorded evidence.
    OWNERSHIP_INDETERMINATE = "ownership_indeterminate"


class AmbiguityDisposition(StrEnum):
    """What an operator settles one ambiguity with. Exactly three, and no fourth.

    **There is no `DELETE`, no `IGNORE`, no `COPY` and no `QUARANTINE`, and the
    absence is the contract.** Section 10.11's rule that nothing on this plane is
    destroyed holds through an inversion exactly as it holds through a merge, so
    a disposition that removed a row would be the one path around it; a
    disposition that duplicated one would manufacture evidence that no source
    ever produced. What is left is the three answers a person can actually give
    about a record whose owner the ledger cannot prove.

    `LEAVE_UNRESOLVED` is an answer and not an omission. RI v0.2 section 15.4
    asks a split to preserve shared and ambiguous evidence rather than force it
    onto a nearest identity, and a settlement row saying "the evidence does not
    establish an owner" is what preserving it looks like in the record. A missing
    disposition is refused instead, because silence is not a decision.
    """

    #: Bind the record to one named participant of this split.
    ASSIGN_TO_ENTITY = "assign_to_entity"
    #: Leave the record where it stands as evidence more than one identity
    #: shares. Admissible only where the record family's own contract supports
    #: non-exclusive semantics; see `_DISPOSITIONS_BY_FAMILY`.
    PRESERVE_SHARED = "preserve_shared"
    #: Record that the evidence does not establish an owner, and change nothing.
    LEAVE_UNRESOLVED = "leave_unresolved"


#: Which dispositions each record family admits, and `PRESERVE_SHARED` is the
#: column the evidence actually decides.
#:
#: **`PRESERVE_SHARED` is legal for `OBSERVATION` and nowhere else.** The sole
#: textual warrant for a shared outcome is RI v0.2 section 15.4 line 1186,
#: "preserve shared and ambiguous evidence", and it is about *evidence*: an
#: observation is a record of something a source said, and one utterance can
#: mention two identities without either owning it. Every other family on this
#: plane records an exclusive fact about one identity, so "shared" there would
#: mean a second copy -- which section 15.4 line 1187 forbids in the same breath
#: ("avoid duplicating commitments silently").
#:
#: `RELATIONSHIP_MEMORY` is denied on its own specification rather than by
#: analogy: `docs/specs/relationship-memory-v0.1.md` lines 20-22 define a memory
#: as "one durable statement about **one** generalized `Entity`", so a memory
#: shared between two subjects is not a memory this plane can hold. An
#: `IDENTIFIER` is denied because a canonical address is what the resolver
#: matches on, and two identities holding one current address is the ambiguity
#: the plane exists to prevent. A `PROPOSAL` is denied because sharing one would
#: mean copying it, and a copied proposal carries provenance for a request
#: nobody made.
#:
#: `ALIAS`, `ASSIGNMENT` and `RELATIONSHIP` are **default deny**: each *might*
#: support a non-exclusive reading for some subset of its rows -- a
#: non-canonical alias type, a genuinely non-exclusive domain relation -- and
#: none of them carries a column that proves which subset a given row is in. A
#: default that admitted them would be this mapping deciding, per row, a
#: question no recorded evidence answers.
#:
#: `PROPOSAL`, `RELATIONSHIP_MEMORY`, `MEMORY_PROPOSAL` and `MEMORY_CONTEXT_LINK`
#: admit `LEAVE_UNRESOLVED` only, and the reason is a different kind of absence
#: than the "default deny" above: this is not doubt about which rows qualify,
#: it is that **no writer exists to carry out `ASSIGN_TO_ENTITY` for any of
#: them**. `entity_proposals` carries no entity column at all -- there is
#: nothing on the row an assignment could set -- so `PROPOSAL` cannot be
#: attributed no matter how clean the evidence is. `RelationshipMemoryRepository`
#: and `RelationshipMemoryProposalRepository` (`src/my_pa/contracts/ports.py`)
#: expose no update-or-rebind method at all -- the former is read/admit/replay
#: only, the latter is insert-only (`record_proposal`) -- so `RELATIONSHIP_MEMORY`
#: and `MEMORY_PROPOSAL` have no operator-directed writer to move a row to a
#: different entity either, and `MEMORY_CONTEXT_LINK` has none for the same
#: reason. `LEAVE_UNRESOLVED` needs no writer -- it is a settlement row recorded
#: against the ambiguity, not a mutation of the record -- so it is the one
#: disposition these four families can honestly offer today. Extending them to
#: `ASSIGN_TO_ENTITY` is future work that first requires building that writer;
#: claiming the disposition ahead of the writer (as this mapping used to) would
#: admit a choice this revision cannot execute.
#:
#: **RI-ENT-WP-06b's six additions are all default-deny for `PRESERVE_SHARED`,
#: on the same "default deny" reasoning `ALIAS`/`ASSIGNMENT`/`RELATIONSHIP`
#: already state above, restated because none of the six is `OBSERVATION`.**
#: A name, an address, a communication method, an organization profile, a
#: project participation, or a person-organization affiliation is each a
#: record of one exclusive fact about one entity (or, for the two dual-
#: reference families, one exclusive fact about one *pair* of entities) --
#: none of them is evidence of what a source said the way an observation is,
#: and RI v0.2 section 15.4 line 1186's "preserve shared and ambiguous
#: evidence" is textually about evidence, not about facts. No docstring among
#: `EntityName`, `EntityOrganizationProfile`, `EntityAddress`,
#: `EntityCommunicationMethod`, `EntityProjectParticipation`, or
#: `PersonOrganizationAffiliation` (`my_pa.domain.relationship.entity`)
#: describes a non-exclusive reading for any row, so all six get exactly
#: `IDENTIFIER`'s and `ALIAS`'s two dispositions and nothing more.
#:
#: `ENTITY` never appears because an entity's own redirect is provable from the
#: ledger or the split is refused; `REVIEW_CASE` is ledger-only and writes no
#: row; `DERIVED_CONTEXT` is recomputed rather than attributed. A family absent
#: from this mapping offers no disposition, which is why `dispositions_for`
#: answers with an empty tuple rather than raising: "this family is not
#: dispositioned" is a fact a caller acts on, not an error.
_DISPOSITIONS_BY_FAMILY: Final[dict[IdentityEffectFamily, tuple[AmbiguityDisposition, ...]]] = {
    IdentityEffectFamily.IDENTIFIER: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.ALIAS: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.ASSIGNMENT: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.RELATIONSHIP: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.NAME: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.ORGANIZATION_PROFILE: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.ADDRESS: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.COMMUNICATION_METHOD: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.PROJECT_PARTICIPATION: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.PERSON_ORGANIZATION_AFFILIATION: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.OBSERVATION: (
        AmbiguityDisposition.ASSIGN_TO_ENTITY,
        AmbiguityDisposition.PRESERVE_SHARED,
        AmbiguityDisposition.LEAVE_UNRESOLVED,
    ),
    IdentityEffectFamily.PROPOSAL: (AmbiguityDisposition.LEAVE_UNRESOLVED,),
    IdentityEffectFamily.RELATIONSHIP_MEMORY: (AmbiguityDisposition.LEAVE_UNRESOLVED,),
    IdentityEffectFamily.MEMORY_PROPOSAL: (AmbiguityDisposition.LEAVE_UNRESOLVED,),
    IdentityEffectFamily.MEMORY_CONTEXT_LINK: (AmbiguityDisposition.LEAVE_UNRESOLVED,),
}


def dispositions_for(family: IdentityEffectFamily) -> tuple[AmbiguityDisposition, ...]:
    """The dispositions `family` admits, in vocabulary order, or none at all."""
    return _DISPOSITIONS_BY_FAMILY.get(family, ())


class IdentityEffectKind(StrEnum):
    """What one effect did, named by what undoing it would take.

    **Organised by inverse rather than by table**, because the reader this
    vocabulary exists for is `WP-07`. A set of members like
    `alias_reparented`/`identifier_reparented`/`assignment_reparented` would name
    three rows and one operation; `record_family` already says which row, so what
    is left for this column to say is the thing a split needs to know and cannot
    otherwise recover -- which way to run the change.

    What a split needs from each, stated so the ledger's sufficiency is a claim a
    reader can check rather than an assertion:

    * ENTITY_REDIRECTED -- `before_state` holds the merged-away entity's status
      before the merge, and the inverse restores it and clears
      `superseded_by_entity_id`. This is the only effect the survivor's own row
      is *not* the subject of: `SqlEntityRepository.redirect_entity` writes
      `status` and `superseded_by_entity_id` on the merged-away row and touches
      the survivor not at all, so a merge that revised the survivor would be a
      change this vocabulary does not describe -- and adding that behaviour means
      adding a member here rather than reusing one;
    * OWNER_REPARENTED -- a child row moved from a merged-away entity to the
      survivor. `before_state` names the entity it belonged to, and the inverse
      is to give it back. This is the effect kind a redirect-only ledger has
      instead of, which is the shortcut section 22 names;
    * ROW_COALESCED -- a child row left service because the survivor already held
      an equivalent one. `after_state` names the counterpart it was folded into,
      so the inverse can revive this row *and* know which row to stop treating as
      its replacement. Without the counterpart a split would revive a duplicate
      of a row that is still current;
    * SELF_EDGE_SUPERSEDED -- a directed edge whose two ends became the same
      entity. Section 21 requires it to be superseded rather than to survive
      silently, and it is a separate kind from ROW_COALESCED because it was
      folded into nothing: there is no counterpart, and a split restores it by
      un-superseding rather than by un-folding;
    * DEPENDENT_INVALIDATED -- a pending proposal or review case that named an
      identity the merge changed. `before_state` holds the state it was in, and
      the inverse restores that state rather than re-deciding it;
    * DERIVED_STATE_INVALIDATED -- derived context or index state marked stale.
      It is the one kind whose inverse is not a restoration: a split re-marks
      rather than un-marks, because the derived state was stale in both
      directions. It is recorded so that a split knows the set.

    None of these creates or destroys a row, and that is what makes both states
    required on every effect. An effect kind that created a row would carry no
    `before_state`, and admitting a nullable pair for its sake would let every
    other effect be written with half the evidence -- which is the ledger section
    22 forbids, arrived at by permission rather than by intent.
    """

    ENTITY_REDIRECTED = "entity_redirected"
    OWNER_REPARENTED = "owner_reparented"
    ROW_COALESCED = "row_coalesced"
    SELF_EDGE_SUPERSEDED = "self_edge_superseded"
    DEPENDENT_INVALIDATED = "dependent_invalidated"
    DERIVED_STATE_INVALIDATED = "derived_state_invalidated"


@dataclass(frozen=True, slots=True)
class IdentityConflict:
    """One record that blocks a merge, or that the operator must decide.

    Carries no free-text explanation. A conflict is rendered to an operator by
    the application layer, which knows the capability, the locale of the error
    contract and what may be disclosed; a message stored here would be a bounded
    text column on a record whose subject is somebody's identity, and section 28
    is explicit about what accumulates in those.
    """

    kind: IdentityConflictKind
    family: IdentityEffectFamily
    record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, IdentityConflictKind):
            raise ValueError("an identity conflict has a closed kind")
        if not isinstance(self.family, IdentityEffectFamily):
            raise ValueError("an identity conflict names a closed record family")
        validate_identifier(self.record_id)

    @property
    def blocks(self) -> bool:
        """Whether this conflict refuses the merge rather than awaiting a choice."""
        return blocks_merge(self.kind)


def _canonical(value: object) -> str:
    """One JSON encoding of `value` that two processes agree on byte for byte.

    Sorted keys and no separators padding, the same encoding
    `application.service._authoring_digest` already uses for the same purpose.
    `default` is deliberately absent: a value this cannot encode is a value a
    digest would silently stringify differently on a different Python, and a
    digest that depends on `repr` is not a digest anything can be checked against.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def state_digest(state: Mapping[str, object]) -> str:
    """The digest one effect stores beside a recorded state.

    Recomputed by `IdentityEffect` on construction and refused when it disagrees,
    so a row whose state was edited without its digest -- or whose digest was
    edited without its state -- cannot be read back into the domain at all. That
    is the tamper detection the ledger has beyond the append-only trigger: the
    trigger refuses an `UPDATE` through the ordinary path, and this refuses a row
    that arrived some other way.
    """
    return _digest(state)


def effects_digest_for(effects: Iterable[IdentityEffect]) -> str:
    """Bind a complete, ordered effect ledger without binding generated row IDs.

    Split admission uses this together with the operation's settled effect count.
    Omitting ``effect_id`` and ``recorded_at`` makes the digest a statement about
    the canonical mutations, not about incidental identities or one clock read.
    """
    ordered = sorted(effects, key=lambda effect: effect.sequence)
    return _digest(
        [
            {
                "sequence": effect.sequence,
                "family": effect.family.value,
                "record_id": effect.record_id,
                "kind": effect.kind.value,
                "before_state": dict(effect.before_state),
                "after_state": dict(effect.after_state),
                "before_sha256": effect.before_sha256,
                "after_sha256": effect.after_sha256,
            }
            for effect in ordered
        ]
    )


def preview_digest_for(
    *,
    operation_type: IdentityOperationType,
    principal_id: str,
    survivor_entity_id: str,
    expected_survivor_version: int,
    merged_away: Iterable[tuple[str, int]],
    plan_digest: str,
    source_identity_operation_id: str | None = None,
) -> str:
    """The digest a preview is bound by, over exactly the identity it binds.

    **Over the binding and the safe plan fingerprint.** Principal, operation type, survivor
    with the version it was read at, and every merged-away entity with the
    version it was read at -- sorted, so that two requests naming the same
    entities in different orders are the same preview rather than two.

    Deliberately *not* over the reason or evidence references. The affected
    counts and consequences are bound through `plan_digest`; this
    digest exists so that an apply naming a different set of entities, or the
    same entities at different versions, cannot present itself as the preview the
    operator read. Folding the prose in would make an operator who corrected a
    typo in their own reason re-run the whole preview, and would say nothing
    additional about identity.

    The conflicts the preview found are also digested separately by `conflict_digest_for`,
    because they change for a different reason than the binding does: the
    binding changes when the request changes, and the conflicts change when the
    world does.
    """
    if not _SHA256.fullmatch(plan_digest):
        raise ValueError("a preview plan digest is a sha256 digest")
    if source_identity_operation_id is not None:
        validate_identifier(source_identity_operation_id, IdKind.ENTITY_IDENTITY_OPERATION)
    return _digest(
        {
            "operation_type": operation_type.value,
            "principal_id": principal_id,
            "survivor": [survivor_entity_id, expected_survivor_version],
            "merged_away": sorted([entity_id, version] for entity_id, version in merged_away),
            "plan_digest": plan_digest,
            "source_identity_operation_id": source_identity_operation_id,
        }
    )


def conflict_digest_for(conflicts: Iterable[IdentityConflict]) -> str:
    """The digest over everything a preview found that an apply must still answer for.

    Sorted and deduplicated, so it is a digest of a *set*: the analysis that
    produces conflicts walks several record families and nothing orders those
    walks, and a digest that depended on the walk order would differ between two
    previews of an unchanged world.

    What it is for is the second half of section 21's admission rule. The preview
    digest proves the operator authorised these identities at these versions; this
    proves they authorised them knowing *this* set of conflicts. A merge whose
    blocking conflicts appeared between preview and apply -- a concurrent
    identifier claim is the case section 27 names -- produces a different digest
    here while the binding digest still matches, and the apply is refused with
    the versions still agreeing. Without it, the only thing standing between a
    newly-conflicted merge and an apply would be re-running the analysis and
    hoping the second answer is compared to the first.
    """
    return _digest(
        sorted(
            {
                (conflict.kind.value, conflict.family.value, conflict.record_id)
                for conflict in conflicts
            }
        )
    )


def ambiguity_digest_for(
    ambiguities: Iterable[tuple[str, str, str, Sequence[str], Sequence[str], Mapping[str, object]]],
) -> str:
    """The digest over every question a split preview could not answer for itself.

    **The same column `conflict_digest_for` fills for a merge, and deliberately
    so.** A merge's conflicts and a split's ambiguities are one thing seen on two
    operations: the set of records the operator, not the server, has to settle
    before an apply may proceed. `entity_identity_previews.conflict_digest`
    already carries that set for a merge and apply already refuses when it moved,
    so a split binding its ambiguities there inherits the whole staleness
    mechanism rather than adding a second one that could disagree with it.

    A split with no ambiguities digests the empty set and therefore produces
    exactly what `conflict_digest_for(())` produces, which is what previously
    stood in this column. That equality is not a coincidence to be preserved by
    hand -- both digest `sorted(set())` -- and it is why closing this defect
    changes no token on a split whose inverse was already provable.

    `ambiguity_id` is **not** bound. Identifiers are issued per preview, so
    binding them would make the digest differ from any recomputation and the
    check could never pass. What is bound is everything the operator reads and
    answers against: the family, the record, the finding, the admissible
    answers, the admissible targets, and the evidence summary shown beside them.
    Plain tuples rather than a record, on `plan_digest_for`'s argument for
    `groups`: this is a digest input and not a thing the domain otherwise holds.
    """
    return _digest(
        sorted(
            {
                (
                    family,
                    record_id,
                    reason,
                    tuple(sorted(dispositions)),
                    tuple(sorted(targets)),
                    _canonical(dict(evidence)),
                )
                for family, record_id, reason, dispositions, targets, evidence in ambiguities
            }
        )
    )


def plan_digest_for(
    *,
    groups: Iterable[tuple[str, str, int]],
    conflicts: Iterable[IdentityConflict],
    projected_effects: Iterable[IdentityEffectDraft],
) -> str:
    """Digest the complete safe plan an operator sees, without narrative text.

    Groups bind every named family, disposition and exact count. Conflicts bind
    blockers and required choices. Projected effects bind every deterministic
    canonical consequence and its recovery states. All three collections are
    sorted so repository walk order cannot move the token.
    """
    return _digest(
        {
            "groups": sorted((family, disposition, count) for family, disposition, count in groups),
            "conflicts": sorted(
                {
                    (conflict.kind.value, conflict.family.value, conflict.record_id)
                    for conflict in conflicts
                }
            ),
            "projected_effects": sorted(
                (
                    effect.family.value,
                    effect.record_id,
                    effect.kind.value,
                    _canonical(dict(effect.before_state)),
                    _canonical(dict(effect.after_state)),
                )
                for effect in projected_effects
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class IdentityPreview:
    """One persisted, expiring binding between an operator's approval and a world state.

    `expires_at` is **derived and checked, not supplied**: it is `created_at` plus
    `IDENTITY_PREVIEW_LIFETIME` and any other value is refused. A writer that
    could choose the expiry could choose a longer one, and the whole force of a
    fixed fifteen minutes is that no caller decides it.

    `consumed_at` is what stops one approval producing two merges. Section 27
    requires that "a consumed preview cannot produce a materially different
    second operation"; the record's part of that is to have somewhere to say it
    has been used, and the repository's part is to claim it under the same
    transaction that writes the operation.

    **The versions are carried beside the identities rather than derived from
    them**, because that pairing is the thing the apply re-checks. `merged_away`
    is a tuple of `(entity_id, expected_version)` pairs -- the same untyped-pairs
    shape `EntityProposal.payload` uses -- rather than two parallel tuples, which
    is a shape where a caller can drop one element and produce a preview that
    binds the wrong version to the wrong entity while every length check passes.
    """

    preview_id: str
    principal_id: str
    operation_type: IdentityOperationType
    survivor_entity_id: str
    expected_survivor_version: int
    merged_away: tuple[tuple[str, int], ...]
    preview_digest: str
    conflict_digest: str
    plan_digest: str
    created_by: str
    actor_class: ActorClass
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    source_identity_operation_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.preview_id, IdKind.ENTITY_IDENTITY_PREVIEW)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.survivor_entity_id, IdKind.ENTITY)
        if not isinstance(self.operation_type, IdentityOperationType):
            raise ValueError("a preview has a closed operation type")
        if self.source_identity_operation_id is not None:
            validate_identifier(self.source_identity_operation_id, IdKind.ENTITY_IDENTITY_OPERATION)
        if (self.operation_type is IdentityOperationType.SPLIT) != (
            self.source_identity_operation_id is not None
        ):
            raise ValueError("a split preview names exactly one source merge operation")
        if not isinstance(self.actor_class, ActorClass):
            raise ValueError("a preview has a closed actor class")
        if not self.created_by.strip():
            raise ValueError("a preview names who asked for it")
        if self.expected_survivor_version < 1:
            raise ValueError("a preview expects a survivor version that could exist")
        if not 1 <= len(self.merged_away) <= MAX_MERGED_AWAY_ENTITIES:
            raise ValueError(
                f"a preview merges away between 1 and {MAX_MERGED_AWAY_ENTITIES} entities"
            )
        merged_ids = tuple(entity_id for entity_id, _ in self.merged_away)
        for entity_id, expected_version in self.merged_away:
            validate_identifier(entity_id, IdKind.ENTITY)
            if expected_version < 1:
                raise ValueError("a preview expects a merged-away version that could exist")
        if len(set(merged_ids)) != len(merged_ids):
            raise ValueError("a preview names each merged-away entity once")
        if self.survivor_entity_id in merged_ids:
            raise ValueError("a preview does not merge the survivor into itself")
        for digest in (self.preview_digest, self.conflict_digest, self.plan_digest):
            if not _SHA256.fullmatch(digest):
                raise ValueError("a preview digest is a sha256 digest")
        ensure_utc(self.created_at)
        ensure_utc(self.expires_at)
        if self.expires_at != self.created_at + IDENTITY_PREVIEW_LIFETIME:
            raise ValueError("a preview expires exactly fifteen minutes after it was created")
        if self.consumed_at is not None:
            ensure_utc(self.consumed_at)
            if self.consumed_at < self.created_at:
                raise ValueError("a preview cannot be consumed before it was created")

    @property
    def is_consumed(self) -> bool:
        """Whether an operation has already been admitted against this preview."""
        return self.consumed_at is not None

    def is_expired(self, now: datetime) -> bool:
        """Whether `now` is past this preview's fixed expiry.

        Takes the moment as an argument rather than reading a clock, so the
        expiry a caller enforces is the one the caller can also audit -- and so
        that the transaction which consumes a preview compares against the same
        instant it stamps.
        """
        return ensure_utc(now) >= self.expires_at

    def binds(self, digest: str) -> bool:
        """Whether `digest` is the binding this preview was issued for.

        A method rather than an equality the caller writes, because the value
        being compared is the one an operator's client sends back and the
        comparison is the whole admission gate: a caller that compared
        `conflict_digest` here by mistake would accept a merge whose identities
        had changed, and the two columns are adjacent strings of the same shape.
        """
        return digest == self.preview_digest


@dataclass(frozen=True, slots=True)
class IdentityOperation:
    """One admitted identity correction: what was asked, under what authority, and how it ended.

    **`preview_digest` and `idempotency_key` are both here and they are not the
    same mechanism**, which section 23 states as a rule and this record enforces
    as a shape. The digest is a claim about the *world*: these entities held these
    versions. The key is a claim about the *request*: this is the same call I
    made before. `request_digest` is what makes the second claim decidable --
    same key and same digest is the caller retrying and gets the first answer
    back; same key and a different digest is a caller reusing a key for a
    different merge, which is the one case that must be refused rather than
    absorbed. It is the mechanism `entity_mutation_events` already uses, reused
    rather than reinvented.

    `reason` is bounded and `repr=False`. It explains one decision to a later
    reader; a column that could hold a document is a column an ingester
    eventually puts one in, and on this plane the document would be about a
    person.
    """

    identity_operation_id: str
    principal_id: str
    operation_type: IdentityOperationType
    survivor_entity_id: str
    merged_entity_ids: tuple[str, ...]
    preview_id: str
    preview_digest: str
    idempotency_key: str = field(repr=False)
    request_digest: str
    performed_by: str
    actor_class: ActorClass
    correlation_id: str
    audit_id: str
    receipt_id: str
    state: IdentityOperationState
    started_at: datetime
    reason: str | None = field(default=None, repr=False)
    completed_at: datetime | None = None
    source_identity_operation_id: str | None = None
    effect_count: int | None = None
    effects_digest: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.identity_operation_id, IdKind.ENTITY_IDENTITY_OPERATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.survivor_entity_id, IdKind.ENTITY)
        validate_identifier(self.preview_id, IdKind.ENTITY_IDENTITY_PREVIEW)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        validate_identifier(self.receipt_id, IdKind.RECEIPT)
        if not isinstance(self.operation_type, IdentityOperationType):
            raise ValueError("an identity operation has a closed operation type")
        if self.source_identity_operation_id is not None:
            validate_identifier(self.source_identity_operation_id, IdKind.ENTITY_IDENTITY_OPERATION)
        if (self.operation_type is IdentityOperationType.SPLIT) != (
            self.source_identity_operation_id is not None
        ):
            raise ValueError("a split operation names exactly one source merge operation")
        if (self.effect_count is None) != (self.effects_digest is None):
            raise ValueError("an identity operation settles effect count and digest together")
        if self.effect_count is not None:
            if self.effect_count < 1:
                raise ValueError("an identity operation settles at least one effect")
            if self.effects_digest is None or not _SHA256.fullmatch(self.effects_digest):
                raise ValueError("an identity operation effect digest is a sha256 digest")
        if not isinstance(self.state, IdentityOperationState):
            raise ValueError("an identity operation has a closed state")
        if not isinstance(self.actor_class, ActorClass):
            raise ValueError("an identity operation has a closed actor class")
        if not self.performed_by.strip():
            raise ValueError("an identity operation names who performed it")
        if not self.idempotency_key:
            raise ValueError("an identity operation carries an idempotency key")
        for digest in (self.preview_digest, self.request_digest):
            if not _SHA256.fullmatch(digest):
                raise ValueError("an identity operation digest is a sha256 digest")
        if not 1 <= len(self.merged_entity_ids) <= MAX_MERGED_AWAY_ENTITIES:
            raise ValueError(
                f"an identity operation merges away between 1 and "
                f"{MAX_MERGED_AWAY_ENTITIES} entities"
            )
        for entity_id in self.merged_entity_ids:
            validate_identifier(entity_id, IdKind.ENTITY)
        if len(set(self.merged_entity_ids)) != len(self.merged_entity_ids):
            raise ValueError("an identity operation names each merged-away entity once")
        if self.survivor_entity_id in self.merged_entity_ids:
            raise ValueError("an identity operation does not merge the survivor into itself")
        if self.reason is not None:
            if not self.reason.strip():
                raise ValueError("an identity operation reason is not blank")
            if len(self.reason) > ENTITY_CHANGE_REASON_LIMIT:
                raise ValueError("an identity operation reason is bounded")
        ensure_utc(self.started_at)
        # An operation is finished exactly when it has stopped being in progress.
        # Stated as an equivalence rather than as two rules, so that "still
        # running" is a shape a reader can query for rather than the absence of
        # one -- and so a crashed apply cannot be mistaken for a completed merge
        # by a retry that only looked at the state.
        finished = self.state is not IdentityOperationState.IN_PROGRESS
        if finished != (self.completed_at is not None):
            raise ValueError("an identity operation is finished exactly when it names an end")
        if self.completed_at is not None:
            ensure_utc(self.completed_at)
            if self.completed_at < self.started_at:
                raise ValueError("an identity operation cannot end before it started")


@dataclass(frozen=True, slots=True)
class IdentityEffectDraft:
    """One effect an operation intends, before the ledger has ordered it.

    A separate type from `IdentityEffect` because `sequence` is not the writer's
    to choose. An emitter that assigned its own sequence numbers would be
    assigning them in whatever order it walked the affected families, and two
    replays of the same merge would number the same effects differently -- which
    is the determinism section 29 requires as a tested property. `sequence_effects`
    is the only thing that turns a draft into a ledger row, and it is the only
    place the order is decided.
    """

    family: IdentityEffectFamily
    record_id: str
    kind: IdentityEffectKind
    before_state: Mapping[str, object] = field(repr=False)
    after_state: Mapping[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.family, IdentityEffectFamily):
            raise ValueError("an identity effect names a closed record family")
        if not isinstance(self.kind, IdentityEffectKind):
            raise ValueError("an identity effect has a closed kind")
        # No expected kind: `record_id` names a row in whichever family
        # `family` says, and no single kind can express that. What is still
        # checked is that the value is an opaque identifier at all, which is the
        # rule `entity_mutation_events.record_id` applies for the same reason.
        validate_identifier(self.record_id)
        for state in (self.before_state, self.after_state):
            if not isinstance(state, Mapping):
                raise ValueError("an identity effect records each state as an object")
            if not state:
                raise ValueError("an identity effect records a state that says something")
        if self.before_state == self.after_state:
            raise ValueError("an identity effect records a change")


@dataclass(frozen=True, slots=True)
class IdentityEffect:
    """One append-only row of the ledger a split has to invert a merge from.

    **Both states are required and both digests are checked here.** A ledger row
    holding only the state after the change records that something happened and
    not what it was; section 22 calls recording only redirects "faking
    invertibility", and a half-recorded effect is the same failure one row at a
    time. The digests are recomputed on construction and a disagreement is
    refused, so a state edited without its digest -- or a digest edited without
    its state -- cannot be read back into the domain at all.

    `sequence` is assigned by `sequence_effects` and is unique per operation at
    the server. It orders the ledger for a reader and for the inversion `WP-07`
    will run over it; what makes it meaningful is that the same merge replayed
    produces the same numbers against the same effects.
    """

    effect_id: str
    identity_operation_id: str
    principal_id: str
    sequence: int
    family: IdentityEffectFamily
    record_id: str
    kind: IdentityEffectKind
    before_state: Mapping[str, object] = field(repr=False)
    after_state: Mapping[str, object] = field(repr=False)
    before_sha256: str
    after_sha256: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.effect_id, IdKind.ENTITY_IDENTITY_EFFECT)
        validate_identifier(self.identity_operation_id, IdKind.ENTITY_IDENTITY_OPERATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.record_id)
        if not isinstance(self.family, IdentityEffectFamily):
            raise ValueError("an identity effect names a closed record family")
        if not isinstance(self.kind, IdentityEffectKind):
            raise ValueError("an identity effect has a closed kind")
        if self.sequence < 1:
            raise ValueError("an identity effect sequence is positive")
        for state, digest in (
            (self.before_state, self.before_sha256),
            (self.after_state, self.after_sha256),
        ):
            if not isinstance(state, Mapping):
                raise ValueError("an identity effect records each state as an object")
            if not state:
                raise ValueError("an identity effect records a state that says something")
            if not _SHA256.fullmatch(digest):
                raise ValueError("an identity effect state digest is a sha256 digest")
            if state_digest(state) != digest:
                raise ValueError("an identity effect state does not match its recorded digest")
        if self.before_state == self.after_state:
            raise ValueError("an identity effect records a change")
        ensure_utc(self.recorded_at)


#: Where each family falls in the ledger's order, taken from the declaration
#: order of `IdentityEffectFamily` rather than from the member values, so that
#: `ENTITY` sorts first however the values are spelled.
_FAMILY_ORDER: Final = {family: position for position, family in enumerate(IdentityEffectFamily)}


def _order_key(draft: IdentityEffectDraft) -> tuple[int, str, str]:
    """Where one draft falls in the ledger, decided by nothing that varies per run.

    Family first, so `ENTITY` comes first: the redirect is the change every other
    effect on the operation is a consequence of, and a reader walking the ledger
    forwards sees the identity change before what it caused. `WP-07` walks it
    backwards and therefore undoes the consequences before restoring the
    identity, which is the order the entity plane's own guards require --
    `SqlEntityRepository.redirect_entity` refuses to merge into an entity that is
    itself a redirect, so an inversion that restored the identity last is one
    whose intermediate states are all legal.

    Then `record_id`, then `kind`, both of which are total orders over values the
    server issued rather than over anything a caller chose.
    """
    return (_FAMILY_ORDER[draft.family], draft.record_id, draft.kind.value)


def sequence_effects(
    drafts: Iterable[IdentityEffectDraft],
    *,
    identity_operation_id: str,
    principal_id: str,
    recorded_at: datetime,
) -> tuple[IdentityEffect, ...]:
    """Order `drafts` deterministically and number them from one.

    **The determinism is the whole function.** An emitter walks aliases, then
    identifiers, then assignments, and within each walks whatever the database
    returned; nothing in that ordering is stable across two runs, and a ledger
    whose sequence numbers were assigned in walk order would give the same merge
    two different orderings and give `WP-07` no way to tell a re-run from a
    different operation. So the emitter produces a set and this produces the
    order, and `tests/unit/test_identity_correction.py` proves that shuffling the
    input does not move a single number.

    One effect per record: two drafts naming the same family and record are
    refused rather than ordered, because they are a merge that transformed one
    row twice and the ledger cannot say which state to restore. Refusing here
    also makes `_order_key` a total order, so the numbering has no tie to break.

    Effect identifiers are freshly issued and are not part of the ordering. A
    deterministic *identifier* would be an identifier derived from its subject,
    which `issue_identifier` exists to make impossible; what has to be
    reproducible is the sequence, and it is.
    """
    ordered = sorted(drafts, key=_order_key)
    subjects = [(draft.family, draft.record_id) for draft in ordered]
    if len(set(subjects)) != len(subjects):
        raise ValueError("an identity operation records one effect per record")
    return tuple(
        IdentityEffect(
            effect_id=issue_identifier(IdKind.ENTITY_IDENTITY_EFFECT),
            identity_operation_id=identity_operation_id,
            principal_id=principal_id,
            sequence=sequence,
            family=draft.family,
            record_id=draft.record_id,
            kind=draft.kind,
            before_state=draft.before_state,
            after_state=draft.after_state,
            before_sha256=state_digest(draft.before_state),
            after_sha256=state_digest(draft.after_state),
            recorded_at=recorded_at,
        )
        for sequence, draft in enumerate(ordered, start=1)
    )


def sequence_inverse_effects(
    source_effects: Iterable[IdentityEffect],
    *,
    identity_operation_id: str,
    principal_id: str,
    recorded_at: datetime,
) -> tuple[IdentityEffect, ...]:
    """Record an inverse in the exact reverse of its source operation's order."""
    source = sorted(source_effects, key=lambda effect: effect.sequence, reverse=True)
    if [effect.sequence for effect in source] != list(range(len(source), 0, -1)):
        raise ValueError("an inverse source ledger is contiguous")
    return tuple(
        IdentityEffect(
            effect_id=issue_identifier(IdKind.ENTITY_IDENTITY_EFFECT),
            identity_operation_id=identity_operation_id,
            principal_id=principal_id,
            sequence=sequence,
            family=effect.family,
            record_id=effect.record_id,
            kind=effect.kind,
            before_state=effect.after_state,
            after_state=effect.before_state,
            before_sha256=effect.after_sha256,
            after_sha256=effect.before_sha256,
            recorded_at=recorded_at,
        )
        for sequence, effect in enumerate(source, start=1)
    )


#: Families whose ledger `record_id` no longer names the row the effect
#: describes once the effect has been applied, because the row's own stable
#: identity *is* one of the entity references a merge substitutes.
#:
#: `ORGANIZATION_PROFILE` is the sole member. `entity_organization_profiles.
#: entity_id` is both the table's primary key and the reference
#: `reparent_entity_reference` substitutes (see `EntityOrganizationProfile`'s
#: docstring on why the table has no surrogate row identifier), so an
#: `OWNER_REPARENTED` effect's `record_id` necessarily names the row's
#: identity *before* the effect -- the value a write has to find the row by
#: while it is still there -- and the row is found somewhere else by the time
#: any reader asks about it afterward. Every other family keeps a surrogate
#: id (`alias_id`, `entity_name_id`, `participation_id`, and so on) disjoint
#: from the entity references it carries, so `record_id` never moves under a
#: reader and this set stays a singleton unless a future family repeats
#: `EntityOrganizationProfile`'s PK-is-FK shape.
_RECORD_ID_FOLLOWS_ENTITY_SUBSTITUTION: Final = frozenset(
    {IdentityEffectFamily.ORGANIZATION_PROFILE}
)


def current_record_id(effect: IdentityEffect) -> str:
    """Where `effect`'s row is found now, which is not always `effect.record_id`.

    Every reader asking "does this row still look the way the ledger says" or
    "is this row already accounted for" needs the row's *current* identity,
    not the identity the effect recorded it under before the effect ran. For
    every family but `ORGANIZATION_PROFILE` those are the same value and this
    returns `effect.record_id` unchanged; for `ORGANIZATION_PROFILE` the
    current identity is `effect.after_state["entity_id"]` -- the row's own
    primary key, which the effect itself rewrote.

    Used by both directions of the same problem: `infrastructure.persistence.
    entity`'s split-verification reads (`identity_effect_matches_after_state`,
    `restore_identity_effect`) and `application.identity_correction`'s
    post-merge-created discovery (`_post_merge_created`'s `known` set) would
    otherwise each independently misidentify a correctly-reparented
    organization profile as either unprovable or newly created. One function,
    imported by both, so the two halves of that discovery cannot silently
    disagree about which families need it.
    """
    if effect.family in _RECORD_ID_FOLLOWS_ENTITY_SUBSTITUTION:
        return str(effect.after_state["entity_id"])
    return effect.record_id
