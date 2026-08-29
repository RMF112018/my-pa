"""Show an operator exactly what a merge would do, then do exactly that.

**One analysis, two callers, and that is the whole safety argument.** Operator
prompt section 19 requires `entities.merge.preview` to enumerate every
materially affected record family; section 21 requires `entities.merge` to
transform them atomically. Those are not two descriptions of a merge -- they are
the same description read twice, and a second copy of the reasoning inside apply
could disagree with the one the operator read. So `_analyse` is the only place
that decides which row reparents, which coalesces, which is superseded and which
refuses the merge; preview persists a digest of its findings and apply runs it
again and refuses when the findings changed.

**A family is answered, never skipped.** Section 20 lists fifteen record
families and adds one sentence: "do not silently ignore an affected family."
`MergeFamily` therefore has a member for every one of them, `_analyse` returns a
group for every member on every preview, and a family this phase has no
repository binding for reports that -- rather than being absent from a report
that then looks complete. Two of them are answered with a blocker rather than a
transformation, and the difference between blocking a family and passing over
it is the difference between a merge an operator can trust and one they cannot.

**What blocks, and why blocking is the honest answer.** An active external
identifier the survivor already holds as a former one is refused outright, as
section 21 requires. Relationship Memory is no longer an unsupported boundary:
its subject and Entity-context bindings are planned, recorded, and restored as
content-blind effects while immutable origins remain unchanged. Unsupported
families still surface explicitly in the report rather than disappearing.

**A Review case is not one of them, and it used to be.** The reasoning that
blocked it was that closing a proposal and leaving its case standing is a silent
half-transformation -- which is true wherever a case is a record in its own
right. On this plane it is not one: `entity_proposals.review_case_id` is the
case identifier and `entity_proposal_review_cases` derives the case's state,
version and latest disposition from the proposal row and the decision ledger, so
invalidating the proposal presents the case as invalidated in the same
statement. There is no second write to forget. What the merge does record is a
`REVIEW_CASE` effect that writes no row, because section 22's ledger is what a
`WP-RI-07` split reads and it has to be able to say which cases came off a
reviewer's surface. What the merge does *not* record is a `review.decide` row:
nobody decided the case, the ground moved under it, and a synthesized
disposition would be a reviewer's judgement with no reviewer behind it.

**Coalescing is decided by what a duplicate means to each family, and the two
answers come from the two index shapes.** An alias and an identifier record the
value an entity is *known by*: `an_active_alias_is_unique_per_entity_and_type`
and `an_active_external_identifier_binding_is_unique` both say a value is one
fact, so a merged-away row whose value the survivor already holds is that fact
recorded twice and folds into it with lineage. An assignment and a relationship
record a fact *bounded in time* -- effective dates, an end, a successor -- so two
rows with the same descriptive key are two periods of the same arrangement, and
only the active partial unique says they cannot both be current. That is why the
first pair coalesces on the value and the second pair coalesces only where the
active index would otherwise refuse the write.

**The one conflict an operator decides, and the one they cannot.** A merged-away
row that is current, whose value the survivor holds only as a former one, cannot
coalesce without taking a current fact out of service. For an external
identifier section 21 settles it -- "a conflicting active identifier blocks
merge" -- because an address is an addressable claim the resolver matches on and
one identity holding it as both current and former is exactly the ambiguity that
plane exists to prevent. For an alias both readings preserve lineage and the
schema admits either, so the operator chooses, and apply refuses until they have.

**Nothing here decides authority.** `has_operator_authority` is a parameter and
there is no default: section 24 reserves both capabilities to an operator
context, and a service that could assume its own authority would assume it
whenever a caller forgot to say. Review acceptance is not merge execution
authority and this module has no path from one to the other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, cast

from my_pa.application.errors import (
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import (
    AmbiguitySettlement,
    EntitiesRepository,
    PreviewAmbiguity,
    RelationshipMemoryRepository,
)
from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    validate_identifier,
)
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.authoring import MAX_EVIDENCE_REFERENCES
from my_pa.domain.relationship.entity import (
    AliasState,
    Assignment,
    AssignmentState,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityStatus,
    ExternalIdentifier,
    IdentifierState,
    RelationshipState,
)
from my_pa.domain.relationship.governance import (
    ENTITY_CHANGE_REASON_LIMIT,
    ActorClass,
    EntityObservation,
    EntityProposal,
)
from my_pa.domain.relationship.identity_correction import (
    IDENTITY_PREVIEW_LIFETIME,
    MAX_MERGED_AWAY_ENTITIES,
    AmbiguityDisposition,
    AmbiguityReason,
    IdentityConflict,
    IdentityConflictKind,
    IdentityEffect,
    IdentityEffectDraft,
    IdentityEffectFamily,
    IdentityEffectKind,
    IdentityOperation,
    IdentityOperationState,
    IdentityOperationType,
    IdentityPreview,
    ambiguity_digest_for,
    conflict_digest_for,
    dispositions_for,
    effects_digest_for,
    plan_digest_for,
    preview_digest_for,
    sequence_effects,
    state_digest,
)
from my_pa.domain.relationship.proposal_payload import EntityProposalKind, schema_for
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "ConflictChoice",
    "FamilyDisposition",
    "IdentityCorrectionService",
    "MergeAffectedGroup",
    "MergeCommand",
    "MergeFamily",
    "MergePreviewCommand",
    "MergePreviewReport",
    "MergeReceipt",
    "SplitCommand",
    "SplitDisposition",
    "SplitPreviewCommand",
    "SplitPreviewReport",
    "SplitReceipt",
]


class MergeFamily(StrEnum):
    """Every record family a merge preview answers for.

    **Sixteen members for section 20's fifteen lines, and the count is the
    point.** The contract lists survivor entity, merged-away entities, aliases,
    identifiers, assignments, directed relationships, observations,
    unresolved/resolution decisions, Entity proposals, Review cases,
    Relationship Memory references, linked Tasks and Commitments, source links,
    context/index/cache state and re-enrichment consequences; Tasks and
    Commitments are separate members here because they are separate planes with
    separate bindings, and answering them together would let one of them hide
    behind the other's answer.

    Deliberately **not** `IdentityEffectFamily`, whose twelve members are a
    vocabulary about the *ledger*: it names the families a merge can record an
    effect on, so a family this phase cannot transform has no member there and
    could not be named. This enum is the vocabulary of the *report*, and its
    whole job is to be able to name a family in order to say the merge does
    nothing to it, or cannot.
    """

    SURVIVOR_ENTITY = "survivor_entity"
    MERGED_AWAY_ENTITY = "merged_away_entity"
    ALIAS = "alias"
    IDENTIFIER = "identifier"
    ASSIGNMENT = "assignment"
    RELATIONSHIP = "relationship"
    OBSERVATION = "observation"
    RESOLUTION_DECISION = "resolution_decision"
    ENTITY_PROPOSAL = "entity_proposal"
    REVIEW_CASE = "review_case"
    RELATIONSHIP_MEMORY = "relationship_memory"
    TASK = "task"
    COMMITMENT = "commitment"
    SOURCE_LINK = "source_link"
    DERIVED_CONTEXT = "derived_context"
    RE_ENRICHMENT = "re_enrichment"


class FamilyDisposition(StrEnum):
    """What this merge does to one record family.

    Four answers, and `NOT_BOUND` is the one that had to exist. Without it a
    family the current schema gives no way to reach would be reported as
    `UNCHANGED` -- which says "this merge leaves those rows as they are" about
    rows nobody has established exist. `NOT_BOUND` says something different and
    weaker: no binding between this plane and that one exists at this revision,
    so there is nothing for a merge to find. A later work package that creates
    the binding turns the member into `TRANSFORMED` or `BLOCKED`, and the
    difference is visible in the report rather than silent.
    """

    #: This merge changes rows in this family, and each change is in the ledger.
    TRANSFORMED = "transformed"
    #: Rows exist and name a merged-away entity; the merge deliberately leaves
    #: them exactly as recorded.
    UNCHANGED = "unchanged"
    #: No repository binding between this family and the entity plane exists at
    #: this revision.
    NOT_BOUND = "not_bound"
    #: Rows are materially affected and this phase cannot transform them with
    #: reversible lineage. The merge is refused.
    BLOCKED = "blocked"


class ConflictChoice(StrEnum):
    """What an operator decided about one record a merge could go either way on.

    Two members because the ambiguity has exactly two defensible resolutions and
    each is a different ledger entry: `REPARENT` moves the row to the survivor
    and leaves it current, `COALESCE` folds it into the survivor's counterpart
    and takes it out of service. A default would be this module deciding on the
    operator's behalf the one question section 21 reserves to them.
    """

    REPARENT = "reparent"
    COALESCE = "coalesce"


#: Where each family falls in a preview's report, taken from the declaration
#: order of `MergeFamily` rather than from the member values, so the order a
#: reader sees is the order section 20 names them in however they are spelled.
_FAMILY_ORDER: Final = {family: position for position, family in enumerate(MergeFamily)}

#: How many records one merge may report as affected before the preview stops
#: being something a person can read.
#:
#: Not a page size and not a `LIMIT`: exceeding it refuses the preview rather
#: than truncating it, because a truncated merge preview is the one report whose
#: missing half is the part that would have stopped the operator. An identity
#: with more affected rows than this is corrected by narrowing the merge, not by
#: approving a summary of it.
MAX_AFFECTED_RECORDS: Final = 10_000


@dataclass(frozen=True, slots=True)
class MergePreviewCommand:
    """What an operator asks `entities.merge.preview` to look at.

    Carries no actor, no clock and no authority: those are the server's, and a
    command with a field for them is a command a caller can put somebody else's
    name in. The service takes them as arguments instead, on the shape
    `ResolveMentionCommand` established for the same reason.
    """

    principal_id: str
    survivor_entity_id: str
    expected_survivor_version: int
    #: `(entity_id, expected_version)` pairs, one to ten of them. Paired rather
    #: than held as two sequences, on `IdentityPreview`'s argument: parallel
    #: sequences admit a request that binds the wrong version to the wrong
    #: entity while every length check passes.
    merged_away: tuple[tuple[str, int], ...]
    reason: str = field(repr=False)
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MergeCommand:
    """What an operator asks `entities.merge` to perform.

    **`preview_digest` and `idempotency_key` are both here and they answer
    different questions**, which section 23 states as a rule: the digest says
    "the world is still what I was shown", the key says "this is the request I
    already made". Neither substitutes for the other, and a merge admitted on
    one alone is admitted on half its evidence.

    `choices` names one disposition per record the preview reported as requiring
    one. It is a sorted tuple of pairs rather than a mapping so the record is
    hashable and so the request digest depends on content rather than on the
    iteration order of whatever mapping a caller built.
    """

    principal_id: str
    preview_id: str
    preview_digest: str
    idempotency_key: str = field(repr=False)
    reason: str = field(repr=False)
    evidence_refs: tuple[str, ...] = ()
    choices: tuple[tuple[str, ConflictChoice], ...] = ()


@dataclass(frozen=True, slots=True)
class MergeAffectedGroup:
    """One record family, what this merge does to it, and how many rows."""

    family: MergeFamily
    disposition: FamilyDisposition
    record_count: int


@dataclass(frozen=True, slots=True)
class MergePreviewReport:
    """The persisted binding and everything the analysis behind it found."""

    preview: IdentityPreview
    groups: tuple[MergeAffectedGroup, ...]
    conflicts: tuple[IdentityConflict, ...]
    #: What apply would record, in the unordered form `sequence_effects` takes.
    #: The projected redirects, coalescings, self-edge supersessions, dependent
    #: invalidations and derived-state invalidations section 19 asks a preview to
    #: return are all here, distinguished by `kind` -- one enumeration rather
    #: than six lists that could disagree about the same row.
    projected_effects: tuple[IdentityEffectDraft, ...]

    @property
    def blockers(self) -> tuple[IdentityConflict, ...]:
        """The conflicts that refuse this merge outright."""
        return tuple(conflict for conflict in self.conflicts if conflict.blocks)

    @property
    def required_choices(self) -> tuple[str, ...]:
        """The records an apply must carry an explicit disposition for."""
        return tuple(
            sorted(conflict.record_id for conflict in self.conflicts if not conflict.blocks)
        )


@dataclass(frozen=True, slots=True)
class MergeReceipt:
    """One completed merge: what was performed, and everything it did.

    `replayed` is `True` when this answer came from the ledger rather than from
    work. Section 23 requires an identical retry to return the prior result, and
    a caller that could not tell the two apart would have no way to notice that
    its first attempt had in fact succeeded.
    """

    operation: IdentityOperation
    effects: tuple[IdentityEffect, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class SplitPreviewCommand:
    """Request a whole-operation inverse of one completed governed merge."""

    principal_id: str
    source_identity_operation_id: str
    reason: str = field(repr=False)
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SplitDisposition:
    """One operator answer to one question a split preview could not answer itself.

    A record rather than the pair `MergeCommand.choices` uses, because a split's
    answer has three parts and not two: an assignment names where the record
    goes, and the other two dispositions name no entity at all. Frozen so the
    request digest can bind it by content.
    """

    ambiguity_id: str
    disposition: AmbiguityDisposition
    target_entity_id: str | None = None


@dataclass(frozen=True, slots=True)
class SplitCommand:
    """Apply the semantic inverse while advancing persisted concurrency tokens.

    `dispositions` names one settlement per ambiguity the preview persisted --
    no more, no fewer, and apply refuses before its first write when the set
    does not match exactly. This is `MergeCommand.choices`' rule on the
    inverse operation, and deliberately the same rule: a merge that admitted a
    partial set of dispositions and a split that admitted one would be two
    different promises about the same guarantee.
    """

    principal_id: str
    preview_id: str
    preview_digest: str
    idempotency_key: str = field(repr=False)
    reason: str = field(repr=False)
    evidence_refs: tuple[str, ...] = ()
    dispositions: tuple[SplitDisposition, ...] = ()


@dataclass(frozen=True, slots=True)
class SplitPreviewReport:
    preview: IdentityPreview
    source_operation: IdentityOperation
    projected_effects: tuple[IdentityEffectDraft, ...]
    #: Every record whose correct inverse the merge ledger does not prove, as
    #: persisted. `projected_effects` and this are disjoint by construction: a
    #: record the ledger proves is restored without an operator ever seeing it,
    #: and a record it does not prove has no projected effect until they settle
    #: it.
    ambiguities: tuple[PreviewAmbiguity, ...] = ()


@dataclass(frozen=True, slots=True)
class SplitReceipt:
    operation: IdentityOperation
    effects: tuple[IdentityEffect, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class _RowChange:
    """One row transformation, with the ledger entry that records it.

    Carries the draft's four fields plus what the writer needs: the version the
    analysis read the row at, which becomes the guard on the write, and the
    counterpart a coalesced row folds into. Two records rather than one because
    `IdentityEffectDraft` is evidence for a later split and has no business
    carrying a `WHERE` clause.
    """

    family: IdentityEffectFamily
    record_id: str
    kind: IdentityEffectKind
    before_state: Mapping[str, object] = field(repr=False)
    after_state: Mapping[str, object] = field(repr=False)
    #: `None` for the two families whose writer guards itself: an entity
    #: redirect is refused by `redirect_entity`'s own chain and cycle checks, and
    #: a proposal invalidation is refused unless the proposal is still open. Also
    #: `None` for a `REVIEW_CASE` change, which has no writer at all -- it
    #: records that a derived case left a reviewer's surface, and there is no row
    #: for a version to guard.
    expected_version: int | None = None
    coalesced_into: str | None = None

    @property
    def draft(self) -> IdentityEffectDraft:
        """This change as the unordered ledger entry `sequence_effects` orders."""
        return IdentityEffectDraft(
            family=self.family,
            record_id=self.record_id,
            kind=self.kind,
            before_state=self.before_state,
            after_state=self.after_state,
        )


@dataclass(frozen=True, slots=True)
class _SplitAmbiguity:
    """One record a split cannot attribute from the merge ledger, before it is stored.

    Separate from `PreviewAmbiguity` because the identifier is not part of the
    finding: an ambiguity identifier is issued when the preview persists the
    question and is what the operator answers against, while the finding itself
    is re-derived at apply and compared by content. Binding the identifier into
    that comparison would make it fail on every recomputation.
    """

    family: IdentityEffectFamily
    record_id: str
    reason: AmbiguityReason
    allowed_dispositions: tuple[AmbiguityDisposition, ...]
    allowed_target_entity_ids: tuple[str, ...]
    evidence_summary: Mapping[str, object] = field(repr=False)

    @property
    def digest_key(
        self,
    ) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...], Mapping[str, object]]:
        """This finding in the form `ambiguity_digest_for` binds."""
        return (
            self.family.value,
            self.record_id,
            self.reason.value,
            tuple(disposition.value for disposition in self.allowed_dispositions),
            self.allowed_target_entity_ids,
            self.evidence_summary,
        )


@dataclass(frozen=True, slots=True)
class _BoundRecord:
    """One current row a settlement may reassign: its guard, and what it names.

    `entity_ids` is every entity reference on the row and not just its holder,
    because `reparent_entity_reference` substitutes all of them at once and a
    row that already names the target somewhere else cannot be moved onto it
    without collapsing two references into one.
    """

    expected_version: int
    entity_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Assignment:
    """One settled `ASSIGN_TO_ENTITY`, resolved against the world before any write."""

    family: IdentityEffectFamily
    record_id: str
    expected_version: int
    target_entity_id: str


@dataclass(frozen=True, slots=True)
class _Analysis:
    """Everything one reading of the world produced."""

    groups: tuple[MergeAffectedGroup, ...]
    conflicts: tuple[IdentityConflict, ...]
    changes: tuple[_RowChange, ...]


def _plan_digest(analysis: _Analysis) -> str:
    """Bind every safe, operator-visible consequence of one baseline analysis."""
    return plan_digest_for(
        groups=(
            (group.family.value, group.disposition.value, group.record_count)
            for group in analysis.groups
        ),
        conflicts=analysis.conflicts,
        projected_effects=(change.draft for change in analysis.changes),
    )


#: The reason recorded on a proposal an identity correction closed.
#:
#: A fixed sentence rather than the operator's own words. `invalidated_reason`
#: is a stored column on a record about a person, and section 28 keeps narrative
#: text out of what a merge leaves behind; what a later reader needs from this
#: column is *which* mechanism closed the proposal, and that is the same
#: sentence every time.
INVALIDATED_BY_MERGE = "the entity this proposal names was merged away by a governed correction"


def _effect_timestamp(value: datetime | None) -> str | None:
    """One server timestamp in the canonical, bounded ledger representation."""
    if value is None:
        return None
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def _materialize_effect_states(
    changes: Sequence[_RowChange], *, at: datetime, performed_by: str
) -> tuple[_RowChange, ...]:
    """Add apply-time columns so each effect equals the row mutation it records.

    Preview planning cannot know the apply timestamp or authenticated performer.
    Those server-owned values therefore stay outside the preview-plan digest and
    are materialized exactly once, after the bound plan is revalidated and before
    either the canonical rows or their effect ledger are written.
    """
    timestamp = _effect_timestamp(at)
    materialized: list[_RowChange] = []
    versioned_children = {
        IdentityEffectFamily.ALIAS,
        IdentityEffectFamily.IDENTIFIER,
        IdentityEffectFamily.ASSIGNMENT,
        IdentityEffectFamily.RELATIONSHIP,
    }
    for change in changes:
        after = dict(change.after_state)
        if change.family in versioned_children:
            after["updated_at"] = timestamp
        elif change.family is IdentityEffectFamily.PROPOSAL:
            after.update(
                {
                    "invalidated_reason": INVALIDATED_BY_MERGE,
                    "decided_by": performed_by,
                    "decided_at": timestamp,
                }
            )
        materialized.append(replace(change, after_state=after))
    return tuple(materialized)


def _folded(value: str | None) -> str:
    """One descriptive field as the active assignment index compares it.

    `an_active_assignment_is_recorded_once` folds and trims `role`, `discipline`
    and `responsibility_class` and treats NULL and the empty string alike. This
    repeats that expression rather than approximating it: an analysis that
    compared the raw strings would plan two reparentings the index then refuses,
    and the merge would fail at the server after the ledger had already recorded
    what it intended to do.
    """
    return (value or "").strip().lower()


def _alias_key(alias: EntityAlias) -> tuple[str, str]:
    """The value one entity is known by, as `an_active_alias_is_unique_per_entity_and_type`
    keys it."""
    return (alias.alias_type.value, alias.normalized_value)


def _identifier_key(identifier: ExternalIdentifier) -> tuple[str, str]:
    """The address one entity is reachable at, as the active binding index keys it."""
    return (identifier.namespace.value, identifier.normalized_value)


def _counterpart_alias(rows: Sequence[EntityAlias]) -> EntityAlias:
    """Which of the survivor's rows a merged-away alias would fold into.

    The current one where there is one -- there is at most one, by the index --
    and otherwise the lowest identifier. Deterministic on both counts, because a
    coalescing that named a different counterpart on a second run would produce
    a different ledger for the same merge.
    """
    active = [row for row in rows if row.state is AliasState.ACTIVE]
    return min(active or list(rows), key=lambda row: row.alias_id)


def _counterpart_identifier(rows: Sequence[ExternalIdentifier]) -> ExternalIdentifier:
    """`_counterpart_alias`, over the identifier plane's own state vocabulary."""
    active = [row for row in rows if row.state is IdentifierState.ACTIVE]
    return min(active or list(rows), key=lambda row: row.identifier_id)


def plan_entities(survivor_entity_id: str, merged: Sequence[Entity]) -> tuple[_RowChange, ...]:
    """Redirect every merged-away entity at the survivor.

    The survivor's own row is not among these and is never rewritten:
    `SqlEntityRepository.redirect_entity` writes `status` and
    `superseded_by_entity_id` on the merged-away row and touches the survivor
    not at all, and section 21's "survivor Entity ID is retained" is that
    property rather than a second write that happens to preserve it.
    """
    return tuple(
        _RowChange(
            family=IdentityEffectFamily.ENTITY,
            record_id=entity.entity_id,
            kind=IdentityEffectKind.ENTITY_REDIRECTED,
            before_state={
                "status": entity.status.value,
                "superseded_by_entity_id": entity.superseded_by_entity_id,
                "version": entity.version,
            },
            after_state={
                "status": EntityStatus.MERGED_REDIRECT.value,
                "superseded_by_entity_id": survivor_entity_id,
                "version": entity.version + 1,
            },
            expected_version=entity.version,
        )
        for entity in sorted(merged, key=lambda entity: entity.entity_id)
    )


def plan_aliases(
    *,
    survivor_entity_id: str,
    survivor_aliases: Sequence[EntityAlias],
    merged_aliases: Sequence[EntityAlias],
    choices: Mapping[str, ConflictChoice],
) -> tuple[tuple[_RowChange, ...], tuple[IdentityConflict, ...]]:
    """Reparent or coalesce every name form the merged-away entities held.

    **The index is built as the plan is made, not read once at the start.** Two
    merged-away entities can hold the same current name form, and the survivor
    hold none: the first reparents and the second then collides with a row that
    did not exist when the walk began. Seeding from the survivor and adding each
    reparented row is what makes the second one coalesce instead of being
    refused by `an_active_alias_is_unique_per_entity_and_type` after the ledger
    had recorded a reparenting.

    The ambiguous case -- a current name form the survivor holds only as a
    former one -- is returned as a conflict and planned only once the operator
    has chosen. At preview `choices` is empty and the row is reported without a
    projected effect, which is exactly what "this needs your decision" means.
    """
    held: dict[tuple[str, str], list[EntityAlias]] = {}
    for alias in survivor_aliases:
        held.setdefault(_alias_key(alias), []).append(alias)
    changes: list[_RowChange] = []
    conflicts: list[IdentityConflict] = []
    for alias in sorted(merged_aliases, key=lambda row: row.alias_id):
        key = _alias_key(alias)
        counterparts = held.get(key)
        if counterparts is None:
            changes.append(_reparented_alias(alias, survivor_entity_id))
            held[key] = [alias]
            continue
        counterpart = _counterpart_alias(counterparts)
        if alias.state is not AliasState.ACTIVE or counterpart.state is AliasState.ACTIVE:
            changes.append(_coalesced_alias(alias, counterpart.alias_id))
            continue
        conflicts.append(
            IdentityConflict(
                kind=IdentityConflictKind.AMBIGUOUS_DISPOSITION,
                family=IdentityEffectFamily.ALIAS,
                record_id=alias.alias_id,
            )
        )
        chosen = choices.get(alias.alias_id)
        if chosen is ConflictChoice.REPARENT:
            changes.append(_reparented_alias(alias, survivor_entity_id))
            counterparts.append(alias)
        elif chosen is ConflictChoice.COALESCE:
            changes.append(_coalesced_alias(alias, counterpart.alias_id))
    return tuple(changes), tuple(conflicts)


def _reparented_alias(alias: EntityAlias, survivor_entity_id: str) -> _RowChange:
    return _RowChange(
        family=IdentityEffectFamily.ALIAS,
        record_id=alias.alias_id,
        kind=IdentityEffectKind.OWNER_REPARENTED,
        before_state=_alias_state(
            entity_id=alias.entity_id,
            state=alias.state.value,
            version=alias.version,
            successor=alias.superseded_by_alias_id,
            updated_at=alias.updated_at,
        ),
        after_state=_alias_state(
            entity_id=survivor_entity_id,
            state=alias.state.value,
            version=alias.version + 1,
            successor=alias.superseded_by_alias_id,
            updated_at=alias.updated_at,
        ),
        expected_version=alias.version,
    )


def _coalesced_alias(alias: EntityAlias, counterpart_id: str) -> _RowChange:
    return _RowChange(
        family=IdentityEffectFamily.ALIAS,
        record_id=alias.alias_id,
        kind=IdentityEffectKind.ROW_COALESCED,
        before_state=_alias_state(
            entity_id=alias.entity_id,
            state=alias.state.value,
            version=alias.version,
            successor=alias.superseded_by_alias_id,
            updated_at=alias.updated_at,
        ),
        after_state=_alias_state(
            entity_id=alias.entity_id,
            state=AliasState.SUPERSEDED.value,
            version=alias.version + 1,
            successor=counterpart_id,
            updated_at=alias.updated_at,
        ),
        expected_version=alias.version,
        coalesced_into=counterpart_id,
    )


def _alias_state(
    *,
    entity_id: str,
    state: str,
    version: int,
    successor: str | None,
    updated_at: datetime | None,
) -> dict[str, object]:
    """One alias row as the ledger records it, before and after.

    **Every value is supplied by the caller and none is inferred from the
    record.** The two sides of an effect differ in different columns depending on
    what the merge did to the row, and a helper that filled in "the ones you did
    not mention" would make the before state depend on which arguments the
    after state happened to need.

    The same four keys on both sides whatever the effect kind, so a later
    inversion reads one shape per family rather than one per effect. Identifiers,
    a closed-vocabulary state and an integer -- no name form, no display value.
    Section 28 is about what accumulates in a ledger of somebody's identities,
    and `normalized_value` is the name itself.
    """
    return {
        "entity_id": entity_id,
        "state": state,
        "version": version,
        "superseded_by_alias_id": successor,
        "updated_at": _effect_timestamp(updated_at),
    }


def plan_identifiers(
    *,
    survivor_entity_id: str,
    survivor_identifiers: Sequence[ExternalIdentifier],
    merged_identifiers: Sequence[ExternalIdentifier],
) -> tuple[tuple[_RowChange, ...], tuple[IdentityConflict, ...]]:
    """Reparent or coalesce every address the merged-away entities were reachable at.

    `plan_aliases`' running index, over the identifier plane's own key, and with
    the ambiguous case decided rather than delegated. Section 21 says a
    conflicting active identifier blocks the merge, and this is that arrangement:
    the merged-away entity's current address is one the survivor holds only as a
    former one, so folding it in would retire an identity that is in service and
    reparenting it would leave one entity holding one address as both current and
    former -- the state `an_active_external_identifier_binding_is_unique` and
    `ConflictedIdentifierError` exist to keep the resolver out of.

    The active-against-active arrangement cannot occur while that index stands:
    one address is the current identity of at most one entity per Principal. The
    branch below still covers it, because the index is the only thing making it
    impossible and a merge that assumed the index would be the write that broke
    it if the index were ever narrowed.
    """
    held: dict[tuple[str, str], list[ExternalIdentifier]] = {}
    for identifier in survivor_identifiers:
        held.setdefault(_identifier_key(identifier), []).append(identifier)
    changes: list[_RowChange] = []
    conflicts: list[IdentityConflict] = []
    for identifier in sorted(merged_identifiers, key=lambda row: row.identifier_id):
        key = _identifier_key(identifier)
        counterparts = held.get(key)
        if counterparts is None:
            changes.append(_reparented_identifier(identifier, survivor_entity_id))
            held[key] = [identifier]
            continue
        if identifier.state is IdentifierState.ACTIVE:
            conflicts.append(
                IdentityConflict(
                    kind=IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT,
                    family=IdentityEffectFamily.IDENTIFIER,
                    record_id=identifier.identifier_id,
                )
            )
            continue
        counterpart = _counterpart_identifier(counterparts)
        changes.append(_coalesced_identifier(identifier, counterpart.identifier_id))
    return tuple(changes), tuple(conflicts)


def _reparented_identifier(identifier: ExternalIdentifier, survivor_entity_id: str) -> _RowChange:
    return _RowChange(
        family=IdentityEffectFamily.IDENTIFIER,
        record_id=identifier.identifier_id,
        kind=IdentityEffectKind.OWNER_REPARENTED,
        before_state=_identifier_state(
            entity_id=identifier.entity_id,
            state=identifier.state.value,
            version=identifier.version,
            successor=identifier.superseded_by_identifier_id,
            updated_at=identifier.updated_at,
        ),
        after_state=_identifier_state(
            entity_id=survivor_entity_id,
            state=identifier.state.value,
            version=identifier.version + 1,
            successor=identifier.superseded_by_identifier_id,
            updated_at=identifier.updated_at,
        ),
        expected_version=identifier.version,
    )


def _coalesced_identifier(identifier: ExternalIdentifier, counterpart_id: str) -> _RowChange:
    return _RowChange(
        family=IdentityEffectFamily.IDENTIFIER,
        record_id=identifier.identifier_id,
        kind=IdentityEffectKind.ROW_COALESCED,
        before_state=_identifier_state(
            entity_id=identifier.entity_id,
            state=identifier.state.value,
            version=identifier.version,
            successor=identifier.superseded_by_identifier_id,
            updated_at=identifier.updated_at,
        ),
        after_state=_identifier_state(
            entity_id=identifier.entity_id,
            state=IdentifierState.SUPERSEDED.value,
            version=identifier.version + 1,
            successor=counterpart_id,
            updated_at=identifier.updated_at,
        ),
        expected_version=identifier.version,
        coalesced_into=counterpart_id,
    )


def _identifier_state(
    *,
    entity_id: str,
    state: str,
    version: int,
    successor: str | None,
    updated_at: datetime | None,
) -> dict[str, object]:
    """One identifier row as the ledger records it, on `_alias_state`'s terms.

    `normalized_value` is absent for the reason it is absent there, and it
    matters more here: the value is an address, and a ledger row is the one place
    an address would survive every retirement the plane records.
    """
    return {
        "entity_id": entity_id,
        "state": state,
        "version": version,
        "superseded_by_identifier_id": successor,
        "updated_at": _effect_timestamp(updated_at),
    }


def plan_assignments(
    *,
    survivor_entity_id: str,
    merged_entity_ids: frozenset[str],
    affected: Sequence[Assignment],
    existing_active: Sequence[Assignment],
) -> tuple[_RowChange, ...]:
    """Reparent every assignment the identity change touches, deduplicating the current ones.

    Two columns are substituted, not one. An assignment names the entity that
    holds it *and* the entity it is scoped to, and a merge that rewrote only the
    first would leave somebody else's role scoped to an identity that no longer
    stands on its own.

    Only current rows deduplicate, and that is the difference from the alias and
    identifier planes above. An assignment is a fact bounded in time -- it starts,
    it ends, it can be superseded -- so two ended rows with the same descriptive
    key are two periods of the same arrangement rather than one fact recorded
    twice. What cannot stand is two *current* ones, and
    `an_active_assignment_is_recorded_once` is what says so.
    """
    held = {
        _assignment_key(row, entity_id=row.entity_id, scope_entity_id=row.scope_entity_id): (
            row.assignment_id
        )
        for row in existing_active
    }
    changes: list[_RowChange] = []
    for assignment in sorted(affected, key=lambda row: row.assignment_id):
        entity_id = _substituted(assignment.entity_id, merged_entity_ids, survivor_entity_id)
        scope_entity_id = _substituted_scope(
            assignment.scope_entity_id, merged_entity_ids, survivor_entity_id
        )
        if (entity_id, scope_entity_id) == (assignment.entity_id, assignment.scope_entity_id):
            continue
        if assignment.state is AssignmentState.ACTIVE:
            key = _assignment_key(assignment, entity_id=entity_id, scope_entity_id=scope_entity_id)
            counterpart = held.get(key)
            if counterpart is not None:
                changes.append(_coalesced_assignment(assignment, counterpart))
                continue
            held[key] = assignment.assignment_id
        changes.append(
            _RowChange(
                family=IdentityEffectFamily.ASSIGNMENT,
                record_id=assignment.assignment_id,
                kind=IdentityEffectKind.OWNER_REPARENTED,
                before_state=_assignment_state(
                    entity_id=assignment.entity_id,
                    scope_entity_id=assignment.scope_entity_id,
                    state=assignment.state.value,
                    version=assignment.version,
                    successor=assignment.superseded_by_assignment_id,
                    updated_at=assignment.updated_at,
                ),
                after_state=_assignment_state(
                    entity_id=entity_id,
                    scope_entity_id=scope_entity_id,
                    state=assignment.state.value,
                    version=assignment.version + 1,
                    successor=assignment.superseded_by_assignment_id,
                    updated_at=assignment.updated_at,
                ),
                expected_version=assignment.version,
            )
        )
    return tuple(changes)


def _assignment_key(
    assignment: Assignment, *, entity_id: str, scope_entity_id: str | None
) -> tuple[str, ...]:
    """`an_active_assignment_is_recorded_once`, restated over a domain record.

    The two entity references are supplied rather than read off the record,
    because the key that decides a collision is the one the row will hold *after*
    the substitution and the one it holds now is the one that no longer applies.
    """
    return (
        entity_id,
        assignment.assignment_type.value,
        scope_entity_id or "",
        _folded(assignment.role),
        _folded(assignment.discipline),
        _folded(assignment.responsibility_class),
    )


def _coalesced_assignment(assignment: Assignment, counterpart_id: str) -> _RowChange:
    return _RowChange(
        family=IdentityEffectFamily.ASSIGNMENT,
        record_id=assignment.assignment_id,
        kind=IdentityEffectKind.ROW_COALESCED,
        before_state=_assignment_state(
            entity_id=assignment.entity_id,
            scope_entity_id=assignment.scope_entity_id,
            state=assignment.state.value,
            version=assignment.version,
            successor=assignment.superseded_by_assignment_id,
            updated_at=assignment.updated_at,
        ),
        after_state=_assignment_state(
            entity_id=assignment.entity_id,
            scope_entity_id=assignment.scope_entity_id,
            state=AssignmentState.SUPERSEDED.value,
            version=assignment.version + 1,
            successor=counterpart_id,
            updated_at=assignment.updated_at,
        ),
        expected_version=assignment.version,
        coalesced_into=counterpart_id,
    )


def _assignment_state(
    *,
    entity_id: str,
    scope_entity_id: str | None,
    state: str,
    version: int,
    successor: str | None,
    updated_at: datetime | None,
) -> dict[str, object]:
    """One assignment row as the ledger records it. No role, no discipline."""
    return {
        "entity_id": entity_id,
        "scope_entity_id": scope_entity_id,
        "state": state,
        "version": version,
        "superseded_by_assignment_id": successor,
        "updated_at": _effect_timestamp(updated_at),
    }


def plan_relationships(
    *,
    survivor_entity_id: str,
    merged_entity_ids: frozenset[str],
    affected: Sequence[EntityRelationship],
    existing_active: Sequence[EntityRelationship],
) -> tuple[_RowChange, ...]:
    """Reparent every edge the identity change touches, collapsing what became a loop.

    **A merge-created self-edge is superseded because the row cannot be stored
    any other way.** `entity_relationships` carries `from_entity_id <>
    to_entity_id` as a CHECK over every row whatever its state, so an edge whose
    two ends both became the survivor has no reparented form -- and section 21
    asks for exactly this outcome rather than for a row that quietly survives
    pointing at an identity that no longer exists. It is superseded with no
    successor because it was folded into nothing: a later split restores it by
    un-superseding rather than by un-folding, which is why the ledger gives it a
    kind of its own.

    An edge that is already superseded and would become a loop is left exactly as
    it is: the merge changes nothing about it, and a row change that wrote the
    same state back would be a ledger entry recording no change -- which
    `IdentityEffectDraft` refuses, correctly.
    """
    held = {
        _relationship_key(
            row,
            from_entity_id=row.from_entity_id,
            to_entity_id=row.to_entity_id,
            scope_entity_id=row.scope_entity_id,
        ): row.relationship_id
        for row in existing_active
    }
    changes: list[_RowChange] = []
    for edge in sorted(affected, key=lambda row: row.relationship_id):
        from_entity_id = _substituted(edge.from_entity_id, merged_entity_ids, survivor_entity_id)
        to_entity_id = _substituted(edge.to_entity_id, merged_entity_ids, survivor_entity_id)
        scope_entity_id = _substituted_scope(
            edge.scope_entity_id, merged_entity_ids, survivor_entity_id
        )
        if (from_entity_id, to_entity_id, scope_entity_id) == (
            edge.from_entity_id,
            edge.to_entity_id,
            edge.scope_entity_id,
        ):
            continue
        if from_entity_id == to_entity_id:
            if edge.state is RelationshipState.SUPERSEDED:
                continue
            changes.append(
                _RowChange(
                    family=IdentityEffectFamily.RELATIONSHIP,
                    record_id=edge.relationship_id,
                    kind=IdentityEffectKind.SELF_EDGE_SUPERSEDED,
                    before_state=_edge_state(edge),
                    after_state=_relationship_state(
                        from_entity_id=edge.from_entity_id,
                        to_entity_id=edge.to_entity_id,
                        scope_entity_id=edge.scope_entity_id,
                        state=RelationshipState.SUPERSEDED.value,
                        version=edge.version + 1,
                        # No successor. The edge was folded into nothing, and a
                        # split restores it by un-superseding rather than by
                        # un-folding -- which is why the ledger gives it a kind
                        # of its own rather than reusing `ROW_COALESCED`.
                        successor=None,
                        updated_at=edge.updated_at,
                    ),
                    expected_version=edge.version,
                )
            )
            continue
        if edge.state is RelationshipState.ACTIVE:
            key = _relationship_key(
                edge,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                scope_entity_id=scope_entity_id,
            )
            counterpart = held.get(key)
            if counterpart is not None:
                changes.append(_coalesced_relationship(edge, counterpart))
                continue
            held[key] = edge.relationship_id
        changes.append(
            _RowChange(
                family=IdentityEffectFamily.RELATIONSHIP,
                record_id=edge.relationship_id,
                kind=IdentityEffectKind.OWNER_REPARENTED,
                before_state=_edge_state(edge),
                after_state=_relationship_state(
                    from_entity_id=from_entity_id,
                    to_entity_id=to_entity_id,
                    scope_entity_id=scope_entity_id,
                    state=edge.state.value,
                    version=edge.version + 1,
                    successor=edge.superseded_by_relationship_id,
                    updated_at=edge.updated_at,
                ),
                expected_version=edge.version,
            )
        )
    return tuple(changes)


def _relationship_key(
    edge: EntityRelationship,
    *,
    from_entity_id: str,
    to_entity_id: str,
    scope_entity_id: str | None,
) -> tuple[str, ...]:
    """`an_active_entity_relationship_is_recorded_once`, over a domain record.

    The three endpoints are supplied on `_assignment_key`'s argument: the key
    that decides a collision is the one the edge will hold after substitution.

    The *opposite* direction of the same pair is a different key and is not a
    duplicate, which is what a directed model is for.
    """
    return (
        from_entity_id,
        edge.relationship_type.value,
        to_entity_id,
        scope_entity_id or "",
    )


def _coalesced_relationship(edge: EntityRelationship, counterpart_id: str) -> _RowChange:
    return _RowChange(
        family=IdentityEffectFamily.RELATIONSHIP,
        record_id=edge.relationship_id,
        kind=IdentityEffectKind.ROW_COALESCED,
        before_state=_edge_state(edge),
        after_state=_relationship_state(
            from_entity_id=edge.from_entity_id,
            to_entity_id=edge.to_entity_id,
            scope_entity_id=edge.scope_entity_id,
            state=RelationshipState.SUPERSEDED.value,
            version=edge.version + 1,
            successor=counterpart_id,
            updated_at=edge.updated_at,
        ),
        expected_version=edge.version,
        coalesced_into=counterpart_id,
    )


def _edge_state(edge: EntityRelationship) -> dict[str, object]:
    """One directed edge exactly as it stands, which is every effect's before state."""
    return _relationship_state(
        from_entity_id=edge.from_entity_id,
        to_entity_id=edge.to_entity_id,
        scope_entity_id=edge.scope_entity_id,
        state=edge.state.value,
        version=edge.version,
        successor=edge.superseded_by_relationship_id,
        updated_at=edge.updated_at,
    )


def _relationship_state(
    *,
    from_entity_id: str,
    to_entity_id: str,
    scope_entity_id: str | None,
    state: str,
    version: int,
    successor: str | None,
    updated_at: datetime | None,
) -> dict[str, object]:
    """One directed edge as the ledger records it. Three endpoints and a state."""
    return {
        "from_entity_id": from_entity_id,
        "to_entity_id": to_entity_id,
        "scope_entity_id": scope_entity_id,
        "state": state,
        "version": version,
        "superseded_by_relationship_id": successor,
        "updated_at": _effect_timestamp(updated_at),
    }


def plan_observations(
    *, survivor_entity_id: str, observations: Sequence[EntityObservation]
) -> tuple[_RowChange, ...]:
    """Rebind every mention that had been placed on a merged-away entity.

    **The observation itself is not rewritten.** `observed_value`,
    `normalized_value`, the source triple and `observed_at` are what a source
    said and when, and section 21 asks a merge to rebind an observation "without
    changing immutable source evidence". What moves is the one column that says
    which identity the mention was decided to be about.

    `resolution_version` is carried into the ledger and is *not* advanced. It
    counts decisions about a mention, and a merge is not a decision about what
    the mention referred to -- it is a change in what that referent is called.
    Carrying it makes the write guarded all the same: a concurrent
    `decide_observation` advances it and this rebinding is then refused rather
    than applied over the top.
    """
    return tuple(
        _RowChange(
            family=IdentityEffectFamily.OBSERVATION,
            record_id=observation.observation_id,
            kind=IdentityEffectKind.OWNER_REPARENTED,
            before_state={
                "entity_id": observation.entity_id,
                "resolution_version": observation.resolution_version,
            },
            after_state={
                "entity_id": survivor_entity_id,
                "resolution_version": observation.resolution_version,
            },
            expected_version=observation.resolution_version,
        )
        for observation in sorted(observations, key=lambda row: row.observation_id)
    )


def plan_proposals(
    proposals: Sequence[EntityProposal],
    review_snapshots: Mapping[str, tuple[int, str | None, bool]] | None = None,
) -> tuple[_RowChange, ...]:
    """Invalidate every open proposal whose subject the identity change removed.

    **Invalidated rather than reprocessed, and rather than left open.** A
    proposal names a mutation of a specific entity; once that entity is a
    redirect the request cannot be accepted as written, and leaving it open would
    put a decision in front of a reviewer that no acceptance could carry out.
    `EntityProposalState.INVALIDATED` is the state the vocabulary already has for
    "the basis failed", and it is not a decision: nobody refused the proposal.

    **A proposal bound to a Review case was a blocker here, and the reasoning
    that made it one is kept rather than deleted, because what changed is worth
    knowing.** It was: the case is as materially affected as the proposal is --
    it is the surface a reviewer sees it on -- invalidating a Review case is
    `WP-RI-05`'s `invalidate` disposition, which did not exist at that revision,
    and closing the proposal while leaving its case standing is the silent
    half-transformation section 20 forbids. `invalidate` exists now, but that is
    not the fact that settles it. **The Entity plane's Review case has no row of
    its own.** `entity_proposals.review_case_id` *is* the case identifier, and
    `entity_proposal_review_cases` derives the case's state, version, escalation
    and latest disposition from the proposal row and the decision ledger. So a
    proposal that becomes `invalidated` presents as an invalidated case on
    `review.list` in the same statement: there is no second record that could be
    left standing, and nothing has to remember to close it. The half a merge
    could have performed silently does not exist here.

    **The Review-case effect is therefore ledger-only, and is emitted all the
    same.** A second `_RowChange` in `IdentityEffectFamily.REVIEW_CASE` writes no
    row -- `_write` guards on the family for exactly that reason -- and exists so
    that section 22's ledger says which cases this merge took off a reviewer's
    surface. Without it a `WP-RI-07` split would restore the proposal with no
    record of which case it had just revived along with it.

    **What is deliberately not written is a decision.** No `review.decide` row
    goes into `entity_proposal_review_decisions`: nobody decided this case, the
    ground moved under it, and a synthesized `invalidate` disposition would put a
    reviewer's judgement on the ledger with no reviewer behind it -- the false
    record that disposition exists to avoid. The proposal's own
    `invalidated_reason` is where the "why" belongs, and `INVALIDATED_BY_MERGE`
    is what goes there.
    """
    changes: list[_RowChange] = []
    for proposal in sorted(proposals, key=lambda row: row.proposal_id):
        changes.append(
            _RowChange(
                family=IdentityEffectFamily.PROPOSAL,
                record_id=proposal.proposal_id,
                kind=IdentityEffectKind.DEPENDENT_INVALIDATED,
                before_state={
                    "state": proposal.state.value,
                    "invalidated_reason": proposal.invalidated_reason,
                    "decided_by": proposal.decided_by,
                    "decided_at": _effect_timestamp(proposal.decided_at),
                },
                after_state={
                    "state": _INVALIDATED_STATE,
                    "invalidated_reason": INVALIDATED_BY_MERGE,
                    # Authenticated apply-time values are materialized only after
                    # the preview-bound plan has been revalidated.
                    "decided_by": None,
                    "decided_at": None,
                },
            )
        )
        if proposal.review_case_id is not None:
            review_before: dict[str, object] = {"state": proposal.state.value}
            review_after: dict[str, object] = {"state": _INVALIDATED_STATE}
            if review_snapshots is not None:
                review_version, latest_disposition, escalated = review_snapshots[
                    proposal.review_case_id
                ]
                snapshot_state = {
                    "review_version": review_version,
                    "latest_disposition": latest_disposition,
                    "escalated": escalated,
                }
                review_before.update(snapshot_state)
                review_after.update(snapshot_state)
            changes.append(
                _RowChange(
                    family=IdentityEffectFamily.REVIEW_CASE,
                    record_id=proposal.review_case_id,
                    kind=IdentityEffectKind.DEPENDENT_INVALIDATED,
                    before_state=review_before,
                    after_state=review_after,
                )
            )
    return tuple(changes)


#: The state an invalidated proposal is written in, spelled rather than reached
#: through the enum for the reason every ledger value here is spelled: what the
#: ledger records is what the column held, and the enum is a separate promise
#: that can be widened without those rows changing meaning.
_INVALIDATED_STATE: Final = "invalidated"


def _substituted(entity_id: str, merged_entity_ids: frozenset[str], survivor_entity_id: str) -> str:
    """`entity_id` with a merged-away identity replaced by the survivor."""
    return survivor_entity_id if entity_id in merged_entity_ids else entity_id


def _substituted_scope(
    entity_id: str | None, merged_entity_ids: frozenset[str], survivor_entity_id: str
) -> str | None:
    """`_substituted` over a scope, which is nullable on both records that carry one.

    A separate name rather than a widened return type, because every caller of
    the first one is a column the schema declares `NOT NULL` and a shared
    signature would make each of them handle a `None` the row cannot hold.
    """
    if entity_id is None:
        return None
    return _substituted(entity_id, merged_entity_ids, survivor_entity_id)


_ENTITY_REFERENCE_FIELDS_BY_PROPOSAL_KIND: Final[Mapping[EntityProposalKind, frozenset[str]]] = {
    EntityProposalKind.CREATE_ENTITY: frozenset(),
    EntityProposalKind.UPDATE_ENTITY: frozenset({"entity_id"}),
    EntityProposalKind.BIND_IDENTIFIER: frozenset({"entity_id"}),
    EntityProposalKind.RETIRE_IDENTIFIER: frozenset({"entity_id"}),
    EntityProposalKind.SUPERSEDE_IDENTIFIER: frozenset({"entity_id"}),
    EntityProposalKind.RECORD_ALIAS: frozenset({"entity_id"}),
    EntityProposalKind.RETIRE_ALIAS: frozenset({"entity_id"}),
    EntityProposalKind.SUPERSEDE_ALIAS: frozenset({"entity_id"}),
    EntityProposalKind.RECORD_ASSIGNMENT: frozenset({"entity_id", "scope_entity_id"}),
    EntityProposalKind.REVISE_ASSIGNMENT: frozenset(),
    EntityProposalKind.END_ASSIGNMENT: frozenset(),
    EntityProposalKind.RECORD_RELATIONSHIP: frozenset(
        {"from_entity_id", "to_entity_id", "scope_entity_id"}
    ),
    EntityProposalKind.REVISE_RELATIONSHIP: frozenset(),
    EntityProposalKind.END_RELATIONSHIP: frozenset(),
    EntityProposalKind.RESOLVE_MENTION: frozenset({"entity_id", "rejected_entity_id"}),
    EntityProposalKind.MERGE_ENTITIES: frozenset({"retained_entity_id", "merged_entity_id"}),
    EntityProposalKind.SPLIT_IDENTITY: frozenset({"entity_id"}),
}

_ASSIGNMENT_REFERENCE_PROPOSAL_KINDS: Final = frozenset(
    {EntityProposalKind.REVISE_ASSIGNMENT, EntityProposalKind.END_ASSIGNMENT}
)
_RELATIONSHIP_REFERENCE_PROPOSAL_KINDS: Final = frozenset(
    {EntityProposalKind.REVISE_RELATIONSHIP, EntityProposalKind.END_RELATIONSHIP}
)

if frozenset(_ENTITY_REFERENCE_FIELDS_BY_PROPOSAL_KIND) != frozenset(EntityProposalKind):
    raise RuntimeError("every Entity proposal kind declares its Entity-reference fields")
if any(
    not fields <= schema_for(kind).admitted
    for kind, fields in _ENTITY_REFERENCE_FIELDS_BY_PROPOSAL_KIND.items()
):
    raise RuntimeError("Entity-reference fields belong to their proposal kind's schema")


def _names_a_merged_entity(proposal: EntityProposal, merged_entity_ids: frozenset[str]) -> bool:
    """Whether the typed payload references an entity this merge removes.

    The closed map is kind-aware because an opaque Entity identifier appearing
    in ordinary text is still ordinary text: `create_entity.display_name`, for
    example, creates no reference even when it happens to equal an Entity ID.
    Today's payload contract is flat (`str | bool`), so it admits no nested or
    collection references to walk. A future kind cannot silently bypass this
    decision because module import requires every enum member to have an entry.
    """
    reference_fields = _ENTITY_REFERENCE_FIELDS_BY_PROPOSAL_KIND[proposal.kind]
    return any(
        name in reference_fields and isinstance(value, str) and value in merged_entity_ids
        for name, value in proposal.payload.values
    )


def _payload_identifier(proposal: EntityProposal, field: str) -> str | None:
    return next(
        (
            value
            for name, value in proposal.payload.values
            if name == field and isinstance(value, str)
        ),
        None,
    )


class IdentityCorrectionService:
    """Computes a governed merge, persists what it computed, and performs it once."""

    def __init__(
        self, entities: EntitiesRepository, memories: RelationshipMemoryRepository
    ) -> None:
        self._entities = entities
        # The memory plane is reached through its own port and not through the
        # entity repository, although the question this asks is about entities.
        # Every statement over a memory table belongs to that plane's two
        # persistence modules, and a merge that read `relationship_memories`
        # from the entity repository would make a third -- which is the reach
        # `tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py`
        # exists to make visible rather than convenient.
        self._memories = memories

    def _proposal_is_materially_affected(
        self,
        principal_id: str,
        proposal: EntityProposal,
        merged_entity_ids: frozenset[str],
    ) -> bool:
        """Resolve indirect child targets without treating opaque text as a reference."""
        if _names_a_merged_entity(proposal, merged_entity_ids):
            return True
        if proposal.kind in _ASSIGNMENT_REFERENCE_PROPOSAL_KINDS:
            assignment_id = _payload_identifier(proposal, "assignment_id")
            assignment = (
                None
                if assignment_id is None
                else self._entities.assignment(principal_id, assignment_id)
            )
            return assignment is not None and bool(
                {assignment.entity_id, assignment.scope_entity_id} & merged_entity_ids
            )
        if proposal.kind in _RELATIONSHIP_REFERENCE_PROPOSAL_KINDS:
            relationship_id = _payload_identifier(proposal, "relationship_id")
            relationship = (
                None
                if relationship_id is None
                else self._entities.relationship(principal_id, relationship_id)
            )
            return relationship is not None and bool(
                {
                    relationship.from_entity_id,
                    relationship.to_entity_id,
                    relationship.scope_entity_id,
                }
                & merged_entity_ids
            )
        return False

    # --- preview -------------------------------------------------------------

    def preview(
        self,
        command: MergePreviewCommand,
        *,
        at: datetime,
        requested_by: str,
        actor_class: ActorClass,
        has_operator_authority: bool,
    ) -> MergePreviewReport:
        """Read the whole affected world, persist the binding, and report it.

        The preview is stored before it is returned. Section 19 makes it a
        durable record rather than a computed response, and the reason is what
        apply has to check: an apply arriving with "the same" identities at
        different versions would otherwise be indistinguishable from a replay of
        the preview an operator actually read.
        """
        self._require_operator(has_operator_authority)
        principal_id = command.principal_id
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        merged_away = self._validated_request(command)
        self._require_evidence(principal_id, command.evidence_refs)
        survivor, merged = self._require_current_entities(
            principal_id,
            command.survivor_entity_id,
            command.expected_survivor_version,
            merged_away,
        )
        analysis = self._analyse(principal_id, survivor, merged, choices={})
        plan_digest = _plan_digest(analysis)
        created_at = ensure_utc(at)
        preview = IdentityPreview(
            preview_id=issue_identifier(IdKind.ENTITY_IDENTITY_PREVIEW),
            principal_id=principal_id,
            operation_type=IdentityOperationType.MERGE,
            survivor_entity_id=survivor.entity_id,
            expected_survivor_version=survivor.version,
            merged_away=merged_away,
            preview_digest=preview_digest_for(
                operation_type=IdentityOperationType.MERGE,
                principal_id=principal_id,
                survivor_entity_id=survivor.entity_id,
                expected_survivor_version=survivor.version,
                merged_away=merged_away,
                plan_digest=plan_digest,
            ),
            conflict_digest=conflict_digest_for(analysis.conflicts),
            plan_digest=plan_digest,
            created_by=requested_by,
            actor_class=actor_class,
            created_at=created_at,
            expires_at=created_at + IDENTITY_PREVIEW_LIFETIME,
        )
        self._entities.record_identity_preview(principal_id, preview)
        return MergePreviewReport(
            preview=preview,
            groups=analysis.groups,
            conflicts=analysis.conflicts,
            projected_effects=tuple(change.draft for change in analysis.changes),
        )

    def split_preview(
        self,
        command: SplitPreviewCommand,
        *,
        at: datetime,
        requested_by: str,
        actor_class: ActorClass,
        has_operator_authority: bool,
    ) -> SplitPreviewReport:
        """Persist a content-blind semantic inverse with monotonic concurrency tokens."""
        self._require_operator(has_operator_authority)
        principal_id = command.principal_id
        validate_identifier(command.principal_id, IdKind.PRINCIPAL)
        validate_identifier(command.source_identity_operation_id, IdKind.ENTITY_IDENTITY_OPERATION)
        self._require_reason(command.reason)
        self._require_evidence(command.principal_id, command.evidence_refs)
        source, effects = self._split_source(
            command.principal_id, command.source_identity_operation_id
        )
        provable, ambiguities = self._classify_split_states(principal_id, source, effects)
        survivor = self._entities.get(command.principal_id, source.survivor_entity_id)
        if survivor is None:
            raise NotFoundError(SafeDetail.ENTITY_ID)
        merged_versions = tuple(
            (effect.record_id, cast(int, effect.after_state["version"]))
            for effect in effects
            if effect.family is IdentityEffectFamily.ENTITY
        )
        drafts = _inverse_drafts(provable)
        plan_digest = _split_plan_digest(drafts)
        created_at = ensure_utc(at)
        preview = IdentityPreview(
            preview_id=issue_identifier(IdKind.ENTITY_IDENTITY_PREVIEW),
            principal_id=command.principal_id,
            operation_type=IdentityOperationType.SPLIT,
            survivor_entity_id=source.survivor_entity_id,
            expected_survivor_version=survivor.version,
            merged_away=merged_versions,
            preview_digest=preview_digest_for(
                operation_type=IdentityOperationType.SPLIT,
                principal_id=command.principal_id,
                survivor_entity_id=source.survivor_entity_id,
                expected_survivor_version=survivor.version,
                merged_away=merged_versions,
                plan_digest=plan_digest,
                source_identity_operation_id=source.identity_operation_id,
            ),
            # The column a merge fills with `conflict_digest_for`. A split's
            # ambiguities are the same thing on the inverse operation -- the set
            # the operator, not the server, must settle -- so binding them here
            # gives split apply the staleness check merge already has instead of
            # a second one that could disagree with it. A split with nothing to
            # settle digests the empty set and produces exactly the token
            # `conflict_digest_for(())` produced before this hook was used.
            conflict_digest=ambiguity_digest_for(ambiguity.digest_key for ambiguity in ambiguities),
            plan_digest=plan_digest,
            created_by=requested_by,
            actor_class=actor_class,
            created_at=created_at,
            expires_at=created_at + IDENTITY_PREVIEW_LIFETIME,
            source_identity_operation_id=source.identity_operation_id,
        )
        self._entities.record_identity_preview(command.principal_id, preview)
        recorded = tuple(
            PreviewAmbiguity(
                preview_id=preview.preview_id,
                ambiguity_id=issue_identifier(IdKind.ENTITY_IDENTITY_AMBIGUITY),
                record_family=ambiguity.family,
                record_id=ambiguity.record_id,
                reason=ambiguity.reason.value,
                allowed_dispositions=tuple(
                    disposition.value for disposition in ambiguity.allowed_dispositions
                ),
                allowed_target_entity_ids=ambiguity.allowed_target_entity_ids,
                evidence_summary=ambiguity.evidence_summary,
                created_at=created_at,
            )
            for ambiguity in ambiguities
        )
        if recorded:
            self._entities.record_preview_ambiguities(principal_id, recorded)
        return SplitPreviewReport(preview, source, drafts, recorded)

    def split_apply(
        self,
        command: SplitCommand,
        *,
        at: datetime,
        correlation_id: str,
        audit_id: str,
        performed_by: str,
        actor_class: ActorClass,
        has_operator_authority: bool,
    ) -> SplitReceipt:
        """Atomically restore source semantics with monotonic concurrency tokens."""
        self._require_operator(has_operator_authority)
        principal_id = command.principal_id
        self._require_reason(command.reason)
        self._require_evidence(command.principal_id, command.evidence_refs)
        request_digest = _split_request_digest(command)
        replayed = self._replay(command.principal_id, command.idempotency_key, request_digest)
        if replayed is not None:
            return SplitReceipt(replayed.operation, replayed.effects, True)
        preview = self._entities.identity_preview(command.principal_id, command.preview_id)
        moment = ensure_utc(at)
        if (
            preview is None
            or preview.operation_type is not IdentityOperationType.SPLIT
            or not preview.binds(command.preview_digest)
            or preview.is_expired(moment)
            or preview.is_consumed
            or preview.source_identity_operation_id is None
        ):
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        source, source_effects = self._split_source(
            command.principal_id, preview.source_identity_operation_id
        )
        expected_merged = tuple(
            (effect.record_id, cast(int, effect.after_state["version"]))
            for effect in source_effects
            if effect.family is IdentityEffectFamily.ENTITY
        )
        survivor = self._entities.get(command.principal_id, source.survivor_entity_id)
        if (
            survivor is None
            or survivor.version != preview.expected_survivor_version
            or preview.merged_away != expected_merged
            or preview.preview_digest
            != preview_digest_for(
                operation_type=IdentityOperationType.SPLIT,
                principal_id=preview.principal_id,
                survivor_entity_id=preview.survivor_entity_id,
                expected_survivor_version=preview.expected_survivor_version,
                merged_away=preview.merged_away,
                plan_digest=preview.plan_digest,
                source_identity_operation_id=source.identity_operation_id,
            )
        ):
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        participants = frozenset({source.survivor_entity_id, *source.merged_entity_ids})
        self._entities.serialize_identifier_entity_scopes(command.principal_id, participants)
        provable, ambiguities = self._classify_split_states(principal_id, source, source_effects)
        if (
            ambiguity_digest_for(ambiguity.digest_key for ambiguity in ambiguities)
            != preview.conflict_digest
        ):
            # The world moved between the preview and this apply in a way the
            # entity versions cannot see: a row was changed, or one was created
            # against the survivor. Refused on the digest merge already refuses
            # on, so an operator's dispositions can never settle a question they
            # were not shown.
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        asked = tuple(self._entities.preview_ambiguities(principal_id, preview.preview_id))
        if (
            ambiguity_digest_for(_stored_digest_key(ambiguity) for ambiguity in asked)
            != preview.conflict_digest
        ):
            # The stored questions disagree with the token the operator answered
            # under, which is the one path the repository's own writes do not
            # cover. Recomputing is the only check that can see it.
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        settled = self._validated_dispositions(command.dispositions, asked)
        reassignments = self._resolved_assignments(
            principal_id, source.survivor_entity_id, asked, settled
        )
        drafts = _inverse_drafts(provable)
        if _split_plan_digest(drafts) != preview.plan_digest:
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        if not self._entities.consume_identity_preview(
            command.principal_id, preview.preview_id, at=moment
        ):
            raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        opened = IdentityOperation(
            identity_operation_id=issue_identifier(IdKind.ENTITY_IDENTITY_OPERATION),
            principal_id=command.principal_id,
            operation_type=IdentityOperationType.SPLIT,
            survivor_entity_id=source.survivor_entity_id,
            merged_entity_ids=source.merged_entity_ids,
            preview_id=preview.preview_id,
            preview_digest=preview.preview_digest,
            idempotency_key=command.idempotency_key,
            request_digest=request_digest,
            reason=command.reason,
            performed_by=performed_by,
            actor_class=actor_class,
            correlation_id=correlation_id,
            audit_id=audit_id,
            receipt_id=issue_identifier(IdKind.RECEIPT),
            state=IdentityOperationState.IN_PROGRESS,
            started_at=moment,
            source_identity_operation_id=source.identity_operation_id,
        )
        self._entities.record_identity_operation(command.principal_id, opened)
        restored_states = {(draft.family, draft.record_id): draft.after_state for draft in drafts}
        for effect in reversed(provable):
            if effect.family is IdentityEffectFamily.REVIEW_CASE:
                continue
            if effect.family in _MEMORY_EFFECT_FAMILIES:
                self._memories.restore_identity_effect(
                    command.principal_id,
                    effect,
                    restored_state=restored_states[(effect.family, effect.record_id)],
                )
            else:
                self._entities.restore_identity_effect(command.principal_id, effect)
        for reassignment in reassignments:
            # Only `ASSIGN_TO_ENTITY` writes. `PRESERVE_SHARED` leaves the record
            # exactly where it stands -- that is what preserving shared evidence
            # is -- and `LEAVE_UNRESOLVED` changes nothing by definition. Both
            # are recorded as settlements below, so "nothing was written" and
            # "nothing was decided" stay different facts.
            self._entities.reparent_entity_reference(
                principal_id,
                family=reassignment.family,
                record_id=reassignment.record_id,
                from_entity_ids=frozenset({source.survivor_entity_id}),
                to_entity_id=reassignment.target_entity_id,
                expected_version=reassignment.expected_version,
                at=moment,
            )
        settlements = tuple(
            AmbiguitySettlement(
                identity_operation_id=opened.identity_operation_id,
                ambiguity_id=ambiguity.ambiguity_id,
                record_family=ambiguity.record_family,
                record_id=ambiguity.record_id,
                disposition=settled[ambiguity.ambiguity_id].disposition.value,
                target_entity_id=settled[ambiguity.ambiguity_id].target_entity_id,
                settled_at=moment,
            )
            for ambiguity in asked
        )
        if settlements:
            self._entities.record_ambiguity_settlements(principal_id, settlements)
        effects = _sequence_split_effects(
            drafts,
            identity_operation_id=opened.identity_operation_id,
            principal_id=command.principal_id,
            recorded_at=moment,
        )
        self._entities.record_identity_effects(command.principal_id, effects)
        completed = replace(
            opened,
            state=IdentityOperationState.COMPLETED,
            completed_at=moment,
            effect_count=len(effects),
            effects_digest=effects_digest_for(effects),
        )
        self._entities.complete_identity_operation(command.principal_id, completed)
        return SplitReceipt(completed, effects, False)

    def _split_source(
        self, principal_id: str, source_identity_operation_id: str
    ) -> tuple[IdentityOperation, tuple[IdentityEffect, ...]]:
        source = self._entities.identity_operation(principal_id, source_identity_operation_id)
        if (
            source is None
            or source.operation_type is not IdentityOperationType.MERGE
            or source.state is not IdentityOperationState.COMPLETED
        ):
            raise NotFoundError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        if self._entities.split_for_source_operation(principal_id, source.identity_operation_id):
            raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        effects = tuple(self._entities.identity_effects(principal_id, source.identity_operation_id))
        if (
            source.effect_count is None
            or source.effects_digest is None
            or source.effect_count != len(effects)
            or tuple(effect.sequence for effect in effects) != tuple(range(1, len(effects) + 1))
            or source.effects_digest != effects_digest_for(effects)
        ):
            raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        return source, effects

    def _classify_split_states(
        self,
        principal_id: str,
        source: IdentityOperation,
        effects: Sequence[IdentityEffect],
    ) -> tuple[tuple[IdentityEffect, ...], tuple[_SplitAmbiguity, ...]]:
        """Sort one merge's ledger into what a split can prove and what it cannot.

        **This used to be a blanket refusal, and that was `RI-P2-BLK-001`.** Any
        row whose current state no longer equalled the recorded `after_state`
        refused the whole split, and a row created against the survivor after the
        merge was never looked for at all -- so the one case an inversion most
        needs to handle, a world that moved while two identities were one, was
        the case it could not handle.

        What is unchanged is the deterministic path. Where the recorded
        `after_state` still describes the row, the correct inverse is provable
        from the ledger and the system performs it. That is derived, not chosen:
        offering an operator a decision about a record whose answer the ledger
        already proves would be asking them to authorise something they cannot
        check and could get wrong.

        What is new is the other half. A row that moved is `POST_MERGE_MODIFIED`;
        a row bound to the survivor that the ledger never mentions is
        `POST_MERGE_CREATED`. Both become questions with a bounded set of
        answers, and apply refuses until each has exactly one.
        """
        participants = tuple(sorted({source.survivor_entity_id, *source.merged_entity_ids}))
        provable: list[IdentityEffect] = []
        ambiguities: list[_SplitAmbiguity] = []
        for effect in effects:
            if effect.family in _MEMORY_EFFECT_FAMILIES:
                matched = self._memories.identity_effect_matches_after_state(principal_id, effect)
            else:
                matched = self._entities.identity_effect_matches_after_state(principal_id, effect)
            if matched:
                provable.append(effect)
                continue
            if not dispositions_for(effect.family):
                # Refused, and deliberately so, but the boundary is
                # `dispositions_for` -- the domain-level, per-family truth of
                # which answers a family admits at all -- and not the narrower
                # `_ATTRIBUTABLE_FAMILIES` immediately below. A family raises an
                # ambiguity whenever it has *any* admissible disposition, and
                # `LEAVE_UNRESOLVED` is one such disposition that needs no
                # rebinding writer at all: it is a settlement row recorded
                # against the ambiguity, not a mutation of the record. That is
                # why `PROPOSAL`, `RELATIONSHIP_MEMORY`, `MEMORY_PROPOSAL` and
                # `MEMORY_CONTEXT_LINK` are ambiguities here even though none of
                # them has a writer that could execute `ASSIGN_TO_ENTITY` for
                # them (see `_DISPOSITIONS_BY_FAMILY`'s comment). Only `ENTITY`,
                # `REVIEW_CASE` and `DERIVED_CONTEXT` admit no disposition at
                # all -- for them there is no answer an operator could give,
                # so the split still refuses outright instead of asking a
                # question nothing could settle. `_ATTRIBUTABLE_FAMILIES`
                # remains the narrower set of families with actual per-row
                # entity-plane storage; it drives one of `_post_merge_created`'s
                # three discovery mechanisms (the other two cover the four
                # families this comment names) and the `ASSIGN_TO_ENTITY`
                # execution path (`_bound_records`, `reparent_entity_reference`),
                # not whether an ambiguity is raised.
                raise ConflictError(SafeDetail.PREVIEW_STALE)
            ambiguities.append(
                _SplitAmbiguity(
                    family=effect.family,
                    record_id=effect.record_id,
                    reason=AmbiguityReason.POST_MERGE_MODIFIED,
                    allowed_dispositions=dispositions_for(effect.family),
                    allowed_target_entity_ids=participants,
                    evidence_summary={
                        "source_identity_operation_id": source.identity_operation_id,
                        "source_effect_id": effect.effect_id,
                        "source_effect_sequence": effect.sequence,
                        "recorded_after_sha256": effect.after_sha256,
                    },
                )
            )
        ambiguities.extend(self._post_merge_created(principal_id, source, effects, participants))
        if len(ambiguities) > MAX_AFFECTED_RECORDS:
            # `MAX_AFFECTED_RECORDS`' own rule: a preview past the ceiling is
            # refused rather than truncated, because the missing half of a
            # truncated inversion is the part that would have stopped the
            # operator.
            raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT, SafeDetail.MAX_ITEMS)
        ambiguities.sort(key=lambda ambiguity: (ambiguity.family.value, ambiguity.record_id))
        return tuple(provable), tuple(ambiguities)

    def _post_merge_created(
        self,
        principal_id: str,
        source: IdentityOperation,
        effects: Sequence[IdentityEffect],
        participants: tuple[str, ...],
    ) -> list[_SplitAmbiguity]:
        """Rows now bound to the survivor that the merge's ledger never named.

        **Known limitation, stated rather than hidden.** The tables the five
        `_ATTRIBUTABLE_FAMILIES` walk carry no creation timestamp -- see
        `entity_aliases` and its three siblings, whose only clock column is
        `updated_at` -- and the merge records no effect for rows that already
        belonged to the survivor. So "bound to the survivor and absent from the
        ledger" is the strongest discriminator the persisted state supports for
        them, and it also matches a survivor's own pre-merge rows.
        `RELATIONSHIP_MEMORY`, `MEMORY_PROPOSAL` and `entity_proposals` (the
        `PROPOSAL` table) *do* carry a creation-ish column -- `created_at` on
        the first, `proposed_at` on the other two -- and this method
        deliberately does not read it: a survivor's own row from before the
        merge is exactly as undiscoverable by timestamp as one genuinely
        created afterwards, since neither this method nor the merge ledger
        records when the survivor's own history began. Reading the column
        would narrow some rows correctly and drop others silently, and there is
        no way from here to tell which is which. The consequence, for every
        family this method discovers, is over-reporting, never
        under-reporting: an operator is asked to attribute a record whose owner
        they can see immediately, and no record is silently attributed for
        them.

        **What this method discovers, and how.** `PROPOSAL`, `RELATIONSHIP_MEMORY`,
        `MEMORY_PROPOSAL` and `MEMORY_CONTEXT_LINK` used to be a stated, residual
        gap here -- `_ATTRIBUTABLE_FAMILIES` is the five families with per-row
        entity-plane storage, and a row newly bound to the survivor in one of
        these other four was never looked for, even though a row the merge
        itself *changed* was already caught as `POST_MERGE_MODIFIED` (that path
        reads the effect ledger, not this discovery). Closing it needed two
        more mechanisms beside `EntitiesRepository.records_bound_to_entity_outside`,
        because the four sit on two different repositories and one of them has
        no per-row entity column to query at all:

        * `RELATIONSHIP_MEMORY`, `MEMORY_PROPOSAL` and `MEMORY_CONTEXT_LINK` are
          `RelationshipMemoryRepository.records_bound_to_entity_outside` -- the
          memory plane's own version of the entity plane's method of the same
          name, over the same three columns `plan_identity_merge` reparents
          when a bound entity is merged away (`subject_entity_id` twice,
          `target_id` once).
        * `PROPOSAL` has no such column: `entity_proposals` carries no entity
          reference at all (see `_ATTRIBUTABLE_FAMILIES`'s own comment), only a
          kind-typed payload. So this asks the question the way `preview()`
          already asks whether a merge *materially affects* an open proposal --
          `self._entities.proposals` read whole and
          `_proposal_is_materially_affected` applied per row, here against
          `{survivor_entity_id}` rather than the merged-away set, and over
          every proposal state rather than only the open ones, on the
          over-reporting argument above.

        Every one of the four keeps the narrowed disposition set
        `dispositions_for` already gives it (`LEAVE_UNRESOLVED` only): this
        method finds the row, it does not decide what may be done about it.
        """
        found: list[_SplitAmbiguity] = []
        for family in _ATTRIBUTABLE_FAMILIES:
            known = frozenset(effect.record_id for effect in effects if effect.family is family)
            for record_id in self._entities.records_bound_to_entity_outside(
                principal_id,
                family,
                source.survivor_entity_id,
                known,
                limit=MAX_AFFECTED_RECORDS + 1,
            ):
                found.append(
                    self._created_ambiguity(family, record_id, source, participants, known)
                )
        for family in _MEMORY_EFFECT_FAMILIES:
            known = frozenset(effect.record_id for effect in effects if effect.family is family)
            for record_id in self._memories.records_bound_to_entity_outside(
                principal_id,
                family,
                source.survivor_entity_id,
                known,
                limit=MAX_AFFECTED_RECORDS + 1,
            ):
                found.append(
                    self._created_ambiguity(family, record_id, source, participants, known)
                )
        proposal_known = frozenset(
            effect.record_id for effect in effects if effect.family is IdentityEffectFamily.PROPOSAL
        )
        survivor_only = frozenset({source.survivor_entity_id})
        bound_proposal_ids = sorted(
            proposal.proposal_id
            for proposal in self._entities.proposals(principal_id)
            if proposal.proposal_id not in proposal_known
            and self._proposal_is_materially_affected(principal_id, proposal, survivor_only)
        )
        for record_id in bound_proposal_ids[: MAX_AFFECTED_RECORDS + 1]:
            found.append(
                self._created_ambiguity(
                    IdentityEffectFamily.PROPOSAL, record_id, source, participants, proposal_known
                )
            )
        return found

    @staticmethod
    def _created_ambiguity(
        family: IdentityEffectFamily,
        record_id: str,
        source: IdentityOperation,
        participants: tuple[str, ...],
        known: frozenset[str],
    ) -> _SplitAmbiguity:
        """One `POST_MERGE_CREATED` ambiguity, in the shape every discovery loop above builds."""
        return _SplitAmbiguity(
            family=family,
            record_id=record_id,
            reason=AmbiguityReason.POST_MERGE_CREATED,
            allowed_dispositions=dispositions_for(family),
            allowed_target_entity_ids=participants,
            evidence_summary={
                "source_identity_operation_id": source.identity_operation_id,
                "bound_entity_id": source.survivor_entity_id,
                "recorded_effect_count": len(known),
            },
        )

    # --- apply ---------------------------------------------------------------

    def apply(
        self,
        command: MergeCommand,
        *,
        at: datetime,
        correlation_id: str,
        audit_id: str,
        performed_by: str,
        actor_class: ActorClass,
        has_operator_authority: bool,
    ) -> MergeReceipt:
        """Perform the merge the preview described, or refuse and change nothing.

        **Every refusal happens before the first write.** The idempotency
        lookup, the preview's identity, its expiry, its consumption state, the
        entity versions, the conflict digest and the operator's dispositions are
        all settled while the transaction has written nothing, so a refused merge
        leaves no operation row and no partial ledger. What follows the last
        check is one sequence of writes inside the caller's transaction, and
        section 21's atomicity is that transaction rather than a compensation
        this module would otherwise have to get right.
        """
        self._require_operator(has_operator_authority)
        principal_id = command.principal_id
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        self._require_reason(command.reason)
        self._require_evidence(principal_id, command.evidence_refs)
        choices = self._validated_choices(command.choices)
        request_digest = _request_digest(command)

        replayed = self._replay(principal_id, command.idempotency_key, request_digest)
        if replayed is not None:
            return replayed

        preview = self._entities.identity_preview(principal_id, command.preview_id)
        if preview is None:
            raise NotFoundError(SafeDetail.PREVIEW_STALE)
        moment = ensure_utc(at)
        if not preview.binds(command.preview_digest):
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        if preview.preview_digest != preview_digest_for(
            operation_type=preview.operation_type,
            principal_id=preview.principal_id,
            survivor_entity_id=preview.survivor_entity_id,
            expected_survivor_version=preview.expected_survivor_version,
            merged_away=preview.merged_away,
            plan_digest=preview.plan_digest,
        ):
            # The stored row disagrees with itself. `IdentityPreview` checks the
            # digest's *shape* and not what it is a digest of, so a row edited at
            # the server -- the one path the repository's own writes do not cover
            # -- would otherwise present a binding the operator never approved
            # under a token they did. Recomputing is the only check that can see
            # it, and it costs one hash.
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        if preview.is_expired(moment):
            raise ConflictError(SafeDetail.PREVIEW_EXPIRED)
        if preview.is_consumed:
            raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)

        participant_ids = frozenset(
            {
                preview.survivor_entity_id,
                *(entity_id for entity_id, _ in preview.merged_away),
            }
        )
        self._entities.serialize_identifier_entity_scopes(principal_id, participant_ids)
        survivor, merged = self._require_current_entities(
            principal_id,
            preview.survivor_entity_id,
            preview.expected_survivor_version,
            preview.merged_away,
        )
        # Analyse once under participant-wide Entity-mutation locks to discover
        # the complete claim population, then lock those opaque identifier claim
        # keys and analyse again. Any Entity-reference writer that won before the
        # participant locks is visible here; one arriving later waits for this
        # transaction. The extra claim keys serialize the cross-Entity normalized
        # address collision that participant identity alone cannot cover.
        self._analyse(principal_id, survivor, merged, choices={})
        claims = frozenset(
            (identifier.namespace.value, identifier.normalized_value)
            for entity_id in sorted(participant_ids)
            for identifier in self._entities.external_identifiers(principal_id, entity_id)
        )
        self._entities.serialize_identifier_claim_keys(principal_id, claims)
        survivor, merged = self._require_current_entities(
            principal_id,
            preview.survivor_entity_id,
            preview.expected_survivor_version,
            preview.merged_away,
        )
        baseline = self._analyse(principal_id, survivor, merged, choices={})
        if (
            conflict_digest_for(baseline.conflicts) != preview.conflict_digest
            or _plan_digest(baseline) != preview.plan_digest
        ):
            # The binding still holds and the world moved anyway. A concurrent
            # identifier claim is the case section 27 names, and it is exactly
            # the one the entity versions cannot see: binding an address writes
            # a child row and advances no entity version. Refusing here is what
            # stops a merge from being the write that bypasses the claim.
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        blockers = tuple(conflict for conflict in baseline.conflicts if conflict.blocks)
        if blockers:
            raise ConflictError(*_blocker_details(blockers))
        required = frozenset(
            conflict.record_id for conflict in baseline.conflicts if not conflict.blocks
        )
        if frozenset(choices) != required:
            raise InvalidRequestError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        analysis = self._analyse(principal_id, survivor, merged, choices=choices)

        return self._perform(
            principal_id,
            preview=preview,
            analysis=analysis,
            command=command,
            request_digest=request_digest,
            at=moment,
            correlation_id=correlation_id,
            audit_id=audit_id,
            performed_by=performed_by,
            actor_class=actor_class,
        )

    def _perform(
        self,
        principal_id: str,
        *,
        preview: IdentityPreview,
        analysis: _Analysis,
        command: MergeCommand,
        request_digest: str,
        at: datetime,
        correlation_id: str,
        audit_id: str,
        performed_by: str,
        actor_class: ActorClass,
    ) -> MergeReceipt:
        """Claim the preview, open the operation, change the rows, close the ledger."""
        if not self._entities.consume_identity_preview(principal_id, preview.preview_id, at=at):
            # Another apply claimed it inside this same instant. The guarded
            # update is what decides, rather than a read this transaction took
            # earlier and a write it takes now.
            raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        merged_entity_ids = tuple(entity_id for entity_id, _ in preview.merged_away)
        opened = IdentityOperation(
            identity_operation_id=issue_identifier(IdKind.ENTITY_IDENTITY_OPERATION),
            principal_id=principal_id,
            operation_type=IdentityOperationType.MERGE,
            survivor_entity_id=preview.survivor_entity_id,
            merged_entity_ids=merged_entity_ids,
            preview_id=preview.preview_id,
            preview_digest=preview.preview_digest,
            idempotency_key=command.idempotency_key,
            request_digest=request_digest,
            reason=command.reason,
            performed_by=performed_by,
            actor_class=actor_class,
            correlation_id=correlation_id,
            audit_id=audit_id,
            receipt_id=issue_identifier(IdKind.RECEIPT),
            state=IdentityOperationState.IN_PROGRESS,
            started_at=at,
        )
        # Opened before the work for two structural reasons rather than one
        # stylistic one. `UNIQUE (principal_id, idempotency_key)` is what makes
        # two concurrent applies under one key serialise here instead of each
        # performing a whole merge and then discovering the other; and the effect
        # ledger's foreign key means no effect is storable until this row exists.
        self._entities.record_identity_operation(principal_id, opened)
        materialized_changes = _materialize_effect_states(
            analysis.changes, at=at, performed_by=performed_by
        )
        self._write(
            principal_id,
            materialized_changes,
            preview=preview,
            at=at,
            performed_by=performed_by,
        )
        effects = sequence_effects(
            (change.draft for change in materialized_changes),
            identity_operation_id=opened.identity_operation_id,
            principal_id=principal_id,
            recorded_at=at,
        )
        self._entities.record_identity_effects(principal_id, effects)
        completed = IdentityOperation(
            identity_operation_id=opened.identity_operation_id,
            principal_id=principal_id,
            operation_type=opened.operation_type,
            survivor_entity_id=opened.survivor_entity_id,
            merged_entity_ids=opened.merged_entity_ids,
            preview_id=opened.preview_id,
            preview_digest=opened.preview_digest,
            idempotency_key=opened.idempotency_key,
            request_digest=opened.request_digest,
            reason=opened.reason,
            performed_by=opened.performed_by,
            actor_class=opened.actor_class,
            correlation_id=opened.correlation_id,
            audit_id=opened.audit_id,
            receipt_id=opened.receipt_id,
            state=IdentityOperationState.COMPLETED,
            started_at=opened.started_at,
            completed_at=at,
            effect_count=len(effects),
            effects_digest=effects_digest_for(effects),
        )
        self._entities.complete_identity_operation(principal_id, completed)
        return MergeReceipt(operation=completed, effects=effects, replayed=False)

    def _write(
        self,
        principal_id: str,
        changes: Sequence[_RowChange],
        *,
        preview: IdentityPreview,
        at: datetime,
        performed_by: str,
    ) -> None:
        """Perform every planned change, in the order the ledger will read them.

        Sorted by the ledger's own key rather than by the order the analysis
        walked the families, so the sequence a reader sees and the sequence the
        writes happened in are the same one -- and a failure part-way through
        leaves a prefix of the ledger's order rather than a prefix of whatever
        order the walk happened to take. `plan_entities`' redirects come first
        for the reason the ledger puts `ENTITY` first: the redirect is the change
        every other effect on this operation is a consequence of.
        """
        merged_entity_ids = frozenset(entity_id for entity_id, _ in preview.merged_away)
        survivor_entity_id = preview.survivor_entity_id
        for change in sorted(changes, key=_ledger_order):
            if change.kind is IdentityEffectKind.ENTITY_REDIRECTED:
                self._entities.redirect_entity(
                    principal_id,
                    change.record_id,
                    survivor_entity_id,
                    expected_version=_guarded_version(change),
                )
            elif change.kind is IdentityEffectKind.DEPENDENT_INVALIDATED:
                # Guarded on the family because this kind now names two effects
                # and only one of them is a write. A `REVIEW_CASE` change is
                # ledger-only: on this plane the case *is* the proposal the same
                # loop has already invalidated -- `entity_proposals.review_case_id`
                # is the case identifier and the case's state is derived from that
                # row -- so there is no second record to close, and the effect
                # exists so `WP-RI-07` knows which cases a split has to revive.
                # Unguarded, this would hand `invalidate_proposal` an `rvw_`
                # identifier and be refused by its own identifier check.
                if change.family is IdentityEffectFamily.PROPOSAL:
                    self._entities.invalidate_proposal(
                        principal_id,
                        change.record_id,
                        reason=INVALIDATED_BY_MERGE,
                        decided_by=performed_by,
                        decided_at=at,
                    )
            elif change.kind is IdentityEffectKind.OWNER_REPARENTED:
                if change.family in _MEMORY_EFFECT_FAMILIES:
                    self._memories.apply_identity_effect(principal_id, change.draft)
                else:
                    self._entities.reparent_entity_reference(
                        principal_id,
                        family=change.family,
                        record_id=change.record_id,
                        from_entity_ids=merged_entity_ids,
                        to_entity_id=survivor_entity_id,
                        expected_version=_guarded_version(change),
                        at=at,
                    )
            else:
                self._entities.supersede_child_record(
                    principal_id,
                    family=change.family,
                    record_id=change.record_id,
                    superseded_by_record_id=change.coalesced_into,
                    expected_version=_guarded_version(change),
                    at=at,
                )

    def _replay(
        self, principal_id: str, idempotency_key: str, request_digest: str
    ) -> MergeReceipt | None:
        """The prior answer this key is already bound to, or `None`.

        Section 23's two rules, in the only order that can tell them apart. The
        same key carrying the same request is a retry and is answered with what
        the first attempt did -- read from the ledger, not recomputed, because
        the world the first attempt changed is not the world it analysed. The
        same key carrying a different request is a caller reusing a key for a
        different merge, and absorbing that would report a merge as performed
        that never was.
        """
        if not idempotency_key:
            raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
        held = self._entities.identity_operation_for_key(principal_id, idempotency_key)
        if held is None:
            return None
        if held.request_digest != request_digest:
            raise ConflictError(SafeDetail.IDEMPOTENCY_CONFLICT)
        if held.state is not IdentityOperationState.COMPLETED:
            raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        recorded = self._entities.identity_effects(principal_id, held.identity_operation_id)
        return MergeReceipt(operation=held, effects=tuple(recorded), replayed=True)

    # --- the one analysis --------------------------------------------------

    def _analyse(
        self,
        principal_id: str,
        survivor: Entity,
        merged: Sequence[Entity],
        *,
        choices: Mapping[str, ConflictChoice],
    ) -> _Analysis:
        """Read every family section 20 names and say what happens to each.

        Every member of `MergeFamily` produces a group on every call, whether or
        not it has anything in it. A report that omitted the empty ones would be
        a report a reader has to know the full list to check.
        """
        merged_entity_ids = frozenset(entity.entity_id for entity in merged)
        groups: list[MergeAffectedGroup] = [
            MergeAffectedGroup(MergeFamily.SURVIVOR_ENTITY, FamilyDisposition.UNCHANGED, 1),
            MergeAffectedGroup(
                MergeFamily.MERGED_AWAY_ENTITY, FamilyDisposition.TRANSFORMED, len(merged)
            ),
        ]
        conflicts: list[IdentityConflict] = []
        changes: list[_RowChange] = list(plan_entities(survivor.entity_id, merged))

        merged_aliases = [
            alias
            for entity in merged
            for alias in self._entities.aliases(principal_id, entity.entity_id)
        ]
        alias_changes, alias_conflicts = plan_aliases(
            survivor_entity_id=survivor.entity_id,
            survivor_aliases=self._entities.aliases(principal_id, survivor.entity_id),
            merged_aliases=merged_aliases,
            choices=choices,
        )
        changes.extend(alias_changes)
        conflicts.extend(alias_conflicts)
        groups.append(
            _group(MergeFamily.ALIAS, len(merged_aliases), bool(alias_changes or alias_conflicts))
        )

        merged_identifiers = [
            identifier
            for entity in merged
            for identifier in self._entities.external_identifiers(principal_id, entity.entity_id)
        ]
        identifier_changes, identifier_conflicts = plan_identifiers(
            survivor_entity_id=survivor.entity_id,
            survivor_identifiers=self._entities.external_identifiers(
                principal_id, survivor.entity_id
            ),
            merged_identifiers=merged_identifiers,
        )
        changes.extend(identifier_changes)
        conflicts.extend(identifier_conflicts)
        groups.append(
            MergeAffectedGroup(
                MergeFamily.IDENTIFIER,
                FamilyDisposition.BLOCKED
                if identifier_conflicts
                else _disposition(bool(identifier_changes)),
                len(merged_identifiers),
            )
        )

        assignments = self._affected_assignments(principal_id, merged_entity_ids)
        assignment_changes = plan_assignments(
            survivor_entity_id=survivor.entity_id,
            merged_entity_ids=merged_entity_ids,
            affected=assignments,
            existing_active=self._existing_assignments(
                principal_id, survivor, merged_entity_ids, assignments
            ),
        )
        changes.extend(assignment_changes)
        groups.append(_group(MergeFamily.ASSIGNMENT, len(assignments), bool(assignment_changes)))

        edges = self._affected_relationships(principal_id, merged_entity_ids)
        relationship_changes = plan_relationships(
            survivor_entity_id=survivor.entity_id,
            merged_entity_ids=merged_entity_ids,
            affected=edges,
            existing_active=self._existing_relationships(
                principal_id, survivor, merged_entity_ids, edges
            ),
        )
        changes.extend(relationship_changes)
        groups.append(_group(MergeFamily.RELATIONSHIP, len(edges), bool(relationship_changes)))

        observations = [
            observation
            for entity in merged
            for observation in self._entities.observations(principal_id, entity.entity_id)
        ]
        observation_changes = plan_observations(
            survivor_entity_id=survivor.entity_id, observations=observations
        )
        changes.extend(observation_changes)
        groups.append(_group(MergeFamily.OBSERVATION, len(observations), bool(observation_changes)))

        # Left exactly as recorded. A resolution decision says what somebody
        # decided about one mention at one moment; rewriting the entity it names
        # would make the record say they decided something else. Section 21 asks
        # for the original lineage and the redirect is what carries a reader from
        # the identity that was decided to the one that stands now.
        groups.append(
            MergeAffectedGroup(
                MergeFamily.RESOLUTION_DECISION,
                FamilyDisposition.UNCHANGED,
                self._entities.resolution_decisions_naming(principal_id, merged_entity_ids),
            )
        )

        open_proposals = [
            proposal
            for proposal in self._entities.proposals(principal_id)
            if proposal.is_open
            and self._proposal_is_materially_affected(principal_id, proposal, merged_entity_ids)
        ]
        review_snapshots: dict[str, tuple[int, str | None, bool]] = {}
        for proposal in open_proposals:
            if proposal.review_case_id is None:
                continue
            snapshot = self._entities.entity_proposal_review_snapshot(
                principal_id, proposal.review_case_id
            )
            if snapshot is None:
                raise ConflictError(SafeDetail.PREVIEW_STALE)
            review_snapshots[proposal.review_case_id] = snapshot
        proposal_changes = plan_proposals(open_proposals, review_snapshots)
        changes.extend(proposal_changes)
        groups.append(
            _group(MergeFamily.ENTITY_PROPOSAL, len(open_proposals), bool(proposal_changes))
        )
        # Counted from the proposals rather than from the planned changes,
        # because the count answers "how many cases are materially affected" and
        # the planner is what decides they are the same number. A proposal that
        # opened no case carries no `review_case_id`, has no identity a reviewer
        # could hold, and is not a case this merge does anything to.
        affected_cases = sum(
            1 for proposal in open_proposals if proposal.review_case_id is not None
        )
        groups.append(_group(MergeFamily.REVIEW_CASE, affected_cases, bool(affected_cases)))

        memory_drafts = self._memories.plan_identity_merge(
            principal_id,
            merged_entity_ids,
            survivor.entity_id,
            survivor.version,
        )
        changes.extend(
            _RowChange(
                family=draft.family,
                record_id=draft.record_id,
                kind=draft.kind,
                before_state=draft.before_state,
                after_state=draft.after_state,
            )
            for draft in memory_drafts
        )
        groups.append(
            MergeAffectedGroup(
                MergeFamily.RELATIONSHIP_MEMORY,
                _disposition(bool(memory_drafts)),
                len(memory_drafts),
            )
        )

        groups.extend(_UNBOUND_GROUPS)
        groups.append(
            MergeAffectedGroup(
                MergeFamily.SOURCE_LINK,
                FamilyDisposition.UNCHANGED,
                self._entities.fact_evidence_links_naming(principal_id, merged_entity_ids),
            )
        )
        # Canonical, version-owned Relationship Memory subjects and Entity
        # context links are included in the content-blind RELATIONSHIP_MEMORY
        # effects above. This family names separate derived cache/index artifacts
        # only; reporting canonical bindings twice would double-count them.
        groups.append(
            MergeAffectedGroup(MergeFamily.DERIVED_CONTEXT, FamilyDisposition.NOT_BOUND, 0)
        )
        groups.append(MergeAffectedGroup(MergeFamily.RE_ENRICHMENT, FamilyDisposition.NOT_BOUND, 0))

        affected = sum(group.record_count for group in groups)
        if affected > MAX_AFFECTED_RECORDS:
            raise InvalidRequestError(SafeDetail.MAX_ITEMS)
        ordered = sorted(groups, key=lambda group: _FAMILY_ORDER[group.family])
        return _Analysis(
            groups=tuple(ordered),
            conflicts=tuple(conflicts),
            changes=tuple(changes),
        )

    # --- reads the analysis composes ---------------------------------------

    def _affected_assignments(
        self, principal_id: str, merged_entity_ids: frozenset[str]
    ) -> list[Assignment]:
        """Every assignment naming a merged-away entity, as holder or as scope.

        Deduplicated by identifier, because one row can be both: an assignment of
        one merged-away entity scoped to another is read twice and is one record.
        """
        found: dict[str, Assignment] = {}
        for entity_id in sorted(merged_entity_ids):
            for assignment in self._entities.assignments(
                principal_id, entity_id, active_only=False
            ):
                found[assignment.assignment_id] = assignment
            for assignment in self._entities.assignments_scoped_by(principal_id, entity_id):
                found[assignment.assignment_id] = assignment
        return [found[key] for key in sorted(found)]

    def _existing_assignments(
        self,
        principal_id: str,
        survivor: Entity,
        merged_entity_ids: frozenset[str],
        affected: Sequence[Assignment],
    ) -> list[Assignment]:
        """The current assignments a reparented one could collide with.

        The survivor's own, plus those of every third entity that holds an
        affected row -- an assignment of somebody else scoped to a merged-away
        project keeps its holder and changes its scope, so the row it might
        duplicate is that holder's, not the survivor's. Rows that are themselves
        being replanned are excluded: they are not counterparts, they are the set
        being placed.
        """
        owners = {survivor.entity_id} | {
            assignment.entity_id
            for assignment in affected
            if assignment.entity_id not in merged_entity_ids
        }
        replanned = {assignment.assignment_id for assignment in affected}
        return [
            assignment
            for owner in sorted(owners)
            for assignment in self._entities.assignments(principal_id, owner, active_only=True)
            if assignment.assignment_id not in replanned
        ]

    def _affected_relationships(
        self, principal_id: str, merged_entity_ids: frozenset[str]
    ) -> list[EntityRelationship]:
        """Every edge naming a merged-away entity at either end or as its scope."""
        found: dict[str, EntityRelationship] = {}
        for entity_id in sorted(merged_entity_ids):
            for edge in self._entities.relationships(principal_id, entity_id):
                found[edge.relationship_id] = edge
            for edge in self._entities.relationships_scoped_by(principal_id, entity_id):
                found[edge.relationship_id] = edge
        return [found[key] for key in sorted(found)]

    def _existing_relationships(
        self,
        principal_id: str,
        survivor: Entity,
        merged_entity_ids: frozenset[str],
        affected: Sequence[EntityRelationship],
    ) -> list[EntityRelationship]:
        """The current edges a reparented one could collide with.

        `_existing_assignments`' rule, over an edge's two endpoints: the key a
        reparented edge takes is decided by both ends, so the rows it might
        duplicate hang off whichever of them the merge leaves alone.
        """
        endpoints = {survivor.entity_id} | {
            entity_id
            for edge in affected
            for entity_id in (edge.from_entity_id, edge.to_entity_id)
            if entity_id not in merged_entity_ids
        }
        replanned = {edge.relationship_id for edge in affected}
        return [
            edge
            for endpoint in sorted(endpoints)
            for edge in self._entities.relationships(principal_id, endpoint)
            if edge.relationship_id not in replanned and edge.state is RelationshipState.ACTIVE
        ]

    # --- request checks -----------------------------------------------------

    def _require_operator(self, has_operator_authority: bool) -> None:
        """Refuse unless the calling context declared operator authority.

        Fails closed and says so with its own token. Section 24 keeps both
        capabilities away from `relationship_standard`, from a reviewer merely
        because a reviewer can decide proposals, from a producer and from an
        ordinary ChatLLM; the registry that publishes them is where that is
        enforced for a request, and this is what makes it true for every caller,
        including one that never went through a registry.
        """
        if not has_operator_authority:
            raise DeniedError(SafeDetail.OPERATOR_REQUIRED)

    def _validated_request(self, command: MergePreviewCommand) -> tuple[tuple[str, int], ...]:
        """The merged-away set, checked as a set rather than as a list.

        Duplicates, the survivor appearing among the entities merged away, an
        empty request and one past ten are all refused here rather than at
        `IdentityPreview`, so a caller gets `invalid_request` naming the field
        instead of an internal error from a record constructor.
        """
        self._require_reason(command.reason)
        validate_identifier(command.survivor_entity_id, IdKind.ENTITY)
        if command.expected_survivor_version < 1:
            raise InvalidRequestError(SafeDetail.EXPECTED_ENTITY_VERSION)
        if not 1 <= len(command.merged_away) <= MAX_MERGED_AWAY_ENTITIES:
            raise InvalidRequestError(SafeDetail.ENTITY_ID, SafeDetail.MAX_ITEMS)
        named: list[str] = []
        for entity_id, expected_version in command.merged_away:
            try:
                validate_identifier(entity_id, IdKind.ENTITY)
            except InvalidIdentifierError as error:
                raise InvalidRequestError(SafeDetail.ENTITY_ID) from error
            if expected_version < 1:
                raise InvalidRequestError(SafeDetail.EXPECTED_ENTITY_VERSION)
            named.append(entity_id)
        if len(set(named)) != len(named):
            raise InvalidRequestError(SafeDetail.ENTITY_ID)
        if command.survivor_entity_id in named:
            raise InvalidRequestError(SafeDetail.ENTITY_ID)
        return tuple(sorted(command.merged_away, key=lambda item: (item[0], item[1])))

    def _require_reason(self, reason: str) -> None:
        """A bounded, non-blank explanation, on `EntityMutationEvent`'s bound."""
        if not reason.strip() or len(reason) > ENTITY_CHANGE_REASON_LIMIT:
            raise InvalidRequestError(SafeDetail.REASON)

    def _require_evidence(self, principal_id: str, evidence_refs: tuple[str, ...]) -> None:
        """Every cited observation exists in this Principal's partition.

        **Checked and not stored, and the gap is stated rather than implied.**
        Neither `entity_identity_previews` nor `entity_identity_operations`
        carries a column for an evidence reference, and the entity plane's own
        mechanism -- a row in `entity_fact_evidence_links` -- would be a record
        this merge created, which the effect ledger's closed kind vocabulary
        cannot express: every kind it declares transforms a row that already
        exists. So the refs are validated at the moment the operator cites them,
        the durable justification is the operation's bounded `reason` and its
        audit event, and the column belongs to whoever adds a create kind.
        """
        if len(evidence_refs) > MAX_EVIDENCE_REFERENCES:
            raise InvalidRequestError(SafeDetail.EVIDENCE_REFS, SafeDetail.MAX_ITEMS)
        if len(set(evidence_refs)) != len(evidence_refs):
            raise InvalidRequestError(SafeDetail.EVIDENCE_REFS)
        for reference in evidence_refs:
            try:
                validate_identifier(reference, IdKind.ENTITY_OBSERVATION)
            except InvalidIdentifierError as error:
                raise InvalidRequestError(SafeDetail.EVIDENCE_REFS) from error
            if self._entities.observation(principal_id, reference) is None:
                # One answer for absent and for another Principal's, on this
                # plane's standing rule: an error that told them apart would let
                # a caller enumerate what somebody else holds.
                raise InvalidRequestError(SafeDetail.EVIDENCE_INVALID)

    def _validated_choices(
        self, choices: tuple[tuple[str, ConflictChoice], ...]
    ) -> dict[str, ConflictChoice]:
        """The operator's dispositions, one per record and no repeats."""
        named = [record_id for record_id, _ in choices]
        if len(set(named)) != len(named):
            raise InvalidRequestError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        for record_id, choice in choices:
            try:
                validate_identifier(record_id)
            except InvalidIdentifierError as error:
                raise InvalidRequestError(SafeDetail.IDENTITY_CORRECTION_CONFLICT) from error
            if not isinstance(choice, ConflictChoice):
                raise InvalidRequestError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
        return dict(choices)

    def _validated_dispositions(
        self,
        dispositions: tuple[SplitDisposition, ...],
        asked: Sequence[PreviewAmbiguity],
    ) -> dict[str, SplitDisposition]:
        """Exactly one admissible settlement per persisted ambiguity, or a refusal.

        `_validated_choices`' shape and `apply`'s set equality in one place,
        because a split's questions are only ever answerable against the rows
        the preview stored: their identifiers are issued there, and the
        admissible answers and targets were computed there and read by the
        operator there. Checking against a fresh analysis instead would check the
        answers against a question nobody was asked.

        Every refusal here happens before the first write.
        """
        named = [decision.ambiguity_id for decision in dispositions]
        if len(set(named)) != len(named):
            raise InvalidRequestError(SafeDetail.DISPOSITION)
        for decision in dispositions:
            try:
                validate_identifier(decision.ambiguity_id, IdKind.ENTITY_IDENTITY_AMBIGUITY)
            except InvalidIdentifierError as error:
                raise InvalidRequestError(SafeDetail.DISPOSITION) from error
            if not isinstance(decision.disposition, AmbiguityDisposition):
                raise InvalidRequestError(SafeDetail.DISPOSITION)
            assigns = decision.disposition is AmbiguityDisposition.ASSIGN_TO_ENTITY
            if assigns is not (decision.target_entity_id is not None):
                # An assignment with no target and a target with no assignment
                # are both records of a decision that was not made, which is the
                # equivalence `an_ambiguity_settlement_names_a_target_exactly_
                # when_it_assigns` states at the server.
                raise InvalidRequestError(SafeDetail.DISPOSITION, SafeDetail.ENTITY_ID)
            if decision.target_entity_id is not None:
                try:
                    validate_identifier(decision.target_entity_id, IdKind.ENTITY)
                except InvalidIdentifierError as error:
                    raise InvalidRequestError(SafeDetail.ENTITY_ID) from error
        settled = {decision.ambiguity_id: decision for decision in dispositions}
        if frozenset(settled) != frozenset(ambiguity.ambiguity_id for ambiguity in asked):
            raise InvalidRequestError(
                SafeDetail.IDENTITY_CORRECTION_CONFLICT, SafeDetail.DISPOSITION
            )
        for ambiguity in asked:
            decision = settled[ambiguity.ambiguity_id]
            if decision.disposition.value not in ambiguity.allowed_dispositions:
                raise InvalidRequestError(SafeDetail.DISPOSITION)
            if (
                decision.target_entity_id is not None
                and decision.target_entity_id not in ambiguity.allowed_target_entity_ids
            ):
                # The admissible targets are this split's own participants, so a
                # target from another Principal fails here for the same reason a
                # target from another merge does: it is not one of the identities
                # this operation restores.
                raise InvalidRequestError(SafeDetail.ENTITY_ID, SafeDetail.DISPOSITION)
        return settled

    def _resolved_assignments(
        self,
        principal_id: str,
        survivor_entity_id: str,
        asked: Sequence[PreviewAmbiguity],
        settled: Mapping[str, SplitDisposition],
    ) -> tuple[_Assignment, ...]:
        """Bind every `ASSIGN_TO_ENTITY` to a row and a guard, or refuse before writing.

        The concurrency token comes from the row as it stands now rather than
        from the ledger, because the whole reason these records are ambiguous is
        that the ledger no longer describes them.

        Two refusals, and both are the same rule stated twice: a settlement this
        transaction cannot carry out is refused while nothing has been written,
        rather than discovered by a write that finds no row. A record that no
        longer binds to the survivor cannot be moved off it, and a record that
        already names the target elsewhere cannot be moved onto it without
        folding two of its references into one -- which is the state a directed
        edge's own `from <> to` refuses.
        """
        wanted = [
            (ambiguity, settled[ambiguity.ambiguity_id].target_entity_id)
            for ambiguity in asked
            if settled[ambiguity.ambiguity_id].disposition is AmbiguityDisposition.ASSIGN_TO_ENTITY
        ]
        if not wanted:
            return ()
        bound: dict[IdentityEffectFamily, dict[str, _BoundRecord]] = {}
        resolved: list[_Assignment] = []
        for ambiguity, target_entity_id in wanted:
            family = ambiguity.record_family
            if family not in bound:
                bound[family] = self._bound_records(principal_id, family, survivor_entity_id)
            record = bound[family].get(ambiguity.record_id)
            if record is None or survivor_entity_id not in record.entity_ids:
                raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
            if target_entity_id is None:  # pragma: no cover - checked by _validated_dispositions
                raise InvalidRequestError(SafeDetail.DISPOSITION)
            if target_entity_id != survivor_entity_id and target_entity_id in record.entity_ids:
                raise ConflictError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)
            resolved.append(
                _Assignment(
                    family=family,
                    record_id=ambiguity.record_id,
                    expected_version=record.expected_version,
                    target_entity_id=target_entity_id,
                )
            )
        return tuple(resolved)

    def _bound_records(
        self, principal_id: str, family: IdentityEffectFamily, entity_id: str
    ) -> dict[str, _BoundRecord]:
        """Every row of `family` currently naming `entity_id`, with its guard.

        Both reads for the two families whose rows name an entity in more than
        one column, on `_affected_assignments`' argument: an assignment scoped to
        the survivor is as much the survivor's row as one it holds, and reading
        only the first would leave a settlement unresolvable that the discovery
        walk had already reported.
        """
        limit = MAX_AFFECTED_RECORDS
        if family is IdentityEffectFamily.ALIAS:
            return {
                alias.alias_id: _BoundRecord(alias.version, frozenset({alias.entity_id}))
                for alias in self._entities.aliases(principal_id, entity_id, limit=limit)
            }
        if family is IdentityEffectFamily.IDENTIFIER:
            return {
                identifier.identifier_id: _BoundRecord(
                    identifier.version, frozenset({identifier.entity_id})
                )
                for identifier in self._entities.external_identifiers(
                    principal_id, entity_id, limit=limit
                )
            }
        if family is IdentityEffectFamily.ASSIGNMENT:
            return {
                assignment.assignment_id: _BoundRecord(
                    assignment.version,
                    frozenset(
                        name
                        for name in (assignment.entity_id, assignment.scope_entity_id)
                        if name is not None
                    ),
                )
                for assignment in (
                    *self._entities.assignments(
                        principal_id, entity_id, active_only=False, limit=limit
                    ),
                    *self._entities.assignments_scoped_by(principal_id, entity_id, limit=limit),
                )
            }
        if family is IdentityEffectFamily.RELATIONSHIP:
            return {
                edge.relationship_id: _BoundRecord(
                    edge.version,
                    frozenset(
                        name
                        for name in (
                            edge.from_entity_id,
                            edge.to_entity_id,
                            edge.scope_entity_id,
                        )
                        if name is not None
                    ),
                )
                for edge in (
                    *self._entities.relationships(principal_id, entity_id, limit=limit),
                    *self._entities.relationships_scoped_by(principal_id, entity_id, limit=limit),
                )
            }
        if family is IdentityEffectFamily.OBSERVATION:
            # `resolution_version` and not `version`: an observation's guard is
            # the token `reparent_entity_reference` reads for it, and a rebinding
            # does not advance it.
            return {
                observation.observation_id: _BoundRecord(
                    observation.resolution_version,
                    frozenset({observation.entity_id})
                    if observation.entity_id is not None
                    else frozenset(),
                )
                for observation in self._entities.observations(principal_id, entity_id, limit=limit)
            }
        raise ConflictError(  # pragma: no cover - _ATTRIBUTABLE_FAMILIES admits five
            SafeDetail.IDENTITY_CORRECTION_CONFLICT
        )

    def _require_current_entities(
        self,
        principal_id: str,
        survivor_entity_id: str,
        expected_survivor_version: int,
        merged_away: tuple[tuple[str, int], ...],
    ) -> tuple[Entity, list[Entity]]:
        """Read the entities this merge names and refuse anything it cannot merge.

        Four refusals with four meanings. An absent or foreign entity is
        `not_found`, identical to the answer for one that does not exist. An
        entity already merged away is `historical_entity`: the row is real and
        the caller's, and merging it again would rewrite a redirect that a reader
        is already following. A version that moved is `preview_stale`, which is
        the token section 21 names for exactly this. And an entity other entities
        already redirect *to* cannot be merged away without leaving a chain that
        never arrives, which is the invariant `redirect_entity` refuses at the
        server -- read here so the operator is told before a preview exists
        rather than by a write that fails.
        """
        survivor = self._entities.get(principal_id, survivor_entity_id)
        if survivor is None:
            raise NotFoundError(SafeDetail.ENTITY_ID)
        if survivor.status is EntityStatus.MERGED_REDIRECT:
            raise ConflictError(SafeDetail.HISTORICAL_ENTITY)
        if survivor.version != expected_survivor_version:
            raise ConflictError(SafeDetail.PREVIEW_STALE, SafeDetail.STALE_VERSION)
        merged: list[Entity] = []
        for entity_id, expected_version in merged_away:
            entity = self._entities.get(principal_id, entity_id)
            if entity is None:
                raise NotFoundError(SafeDetail.ENTITY_ID)
            if entity.status is EntityStatus.MERGED_REDIRECT:
                raise ConflictError(SafeDetail.HISTORICAL_ENTITY)
            if entity.version != expected_version:
                raise ConflictError(SafeDetail.PREVIEW_STALE, SafeDetail.STALE_VERSION)
            merged.append(entity)
        return survivor, merged


def _group(family: MergeFamily, count: int, changed: bool) -> MergeAffectedGroup:
    """One family's group, from what the analysis found and planned."""
    return MergeAffectedGroup(family, _disposition(changed), count)


def _disposition(changed: bool) -> FamilyDisposition:
    """`TRANSFORMED` where a change was planned, `UNCHANGED` otherwise.

    A family with rows and no planned change is genuinely unchanged -- every one
    of its rows already named the survivor, or named nothing this merge moves --
    and `record_count` is what says whether there were any. The disposition
    answers what happens to them, not how many there are, so it does not read the
    count: a family reported `UNCHANGED` with a count of zero and one reported
    `UNCHANGED` with a count of nine are the same statement about each row.
    """
    return FamilyDisposition.TRANSFORMED if changed else FamilyDisposition.UNCHANGED


#: The two families section 20 names that the schema gives no way to reach.
#:
#: `tasks` carries no entity reference at all, and `commitments` names a
#: counterparty under `IdKind.PERSON` -- the WP-9 person substrate, not
#: `IdKind.ENTITY` -- with no foreign key to `entities`. So there is no binding
#: for a merge to find, and section 20's "linked Tasks/Commitments where current
#: repository bindings exist" is answered by saying which bindings do not.
#:
#: Reported rather than omitted, because the difference between "this merge
#: touches no commitment" and "nothing connects a commitment to an identity yet"
#: is exactly what a later work package changes, and a report that omitted the
#: family would look identical before and after.
#:
#: **This is also how a split discharges RI v0.2 section 15.4's "avoid
#: duplicating commitments silently".** It is discharged structurally rather
#: than by a rule the inversion has to remember: with no binding for a merge to
#: find, there is no commitment in any effect for a split to invert and no
#: commitment an operator's disposition could reach. Verified at this revision --
#: `knowledge.commitments.counterparty_person_id` is `IdKind.PERSON` with no
#: foreign key to `knowledge.entities`, and `knowledge.tasks` names no entity at
#: all -- and it stops being true the moment either binding is added, which is
#: the change that would turn these two members into `TRANSFORMED`.
_UNBOUND_GROUPS: Final[tuple[MergeAffectedGroup, ...]] = (
    MergeAffectedGroup(MergeFamily.TASK, FamilyDisposition.NOT_BOUND, 0),
    MergeAffectedGroup(MergeFamily.COMMITMENT, FamilyDisposition.NOT_BOUND, 0),
)


def _ledger_order(change: _RowChange) -> tuple[int, str, str]:
    """Where one change falls in the order `sequence_effects` will number it.

    Restated here rather than reached through the domain's private key function,
    because what this decides is the order of *writes* and what that decides is
    the order of *rows*. They agree, and a test proves they agree; a writer that
    imported the domain's ordering would make that agreement an assumption
    instead.
    """
    return (
        list(IdentityEffectFamily).index(change.family),
        change.record_id,
        change.kind.value,
    )


def _guarded_version(change: _RowChange) -> int:
    """The version a child-row write is guarded on.

    Raises rather than defaulting, because a default here would be a write with
    no optimistic-concurrency predicate at all -- which is the one thing section
    27 forbids outright.
    """
    if change.expected_version is None:
        raise ValueError("a child-row change carries the version it was read at")
    return change.expected_version


def _blocker_details(blockers: Sequence[IdentityConflict]) -> tuple[SafeDetail, ...]:
    """Which tokens a refused merge reports, from the kinds that refused it.

    Two at most: the general one, and `conflicted_identifier` where an address
    was the cause -- because that is the contract's own name for it and a caller
    told only the general token would not know to look at the identifier plane.
    No record identifier and no count: the enumeration is in the preview the
    operator asked for, and an error a client logs is not where somebody's
    identities belong.
    """
    kinds = {blocker.kind for blocker in blockers}
    details = [SafeDetail.IDENTITY_CORRECTION_CONFLICT]
    if IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT in kinds:
        details.append(SafeDetail.CONFLICTED_IDENTIFIER)
    return tuple(details)


def _request_digest(command: MergeCommand) -> str:
    """What makes two applies under one idempotency key the same request.

    Over what the request *asks for* and nothing else: the preview identifier is
    absent, because two previews of the same binding ask for the same merge and a
    retry that re-previewed first is still a retry. The reason, the evidence and
    the dispositions are all in, because changing any of them changes what the
    operator authorised.

    `state_digest` rather than a fourth digest function of its own: it is the
    canonical-JSON SHA-256 the effect ledger already uses, and a second encoding
    would be a second thing to keep in agreement.
    """
    return state_digest(
        {
            "operation_type": IdentityOperationType.MERGE.value,
            "principal_id": command.principal_id,
            "preview_digest": command.preview_digest,
            "reason": command.reason,
            "evidence_refs": sorted(command.evidence_refs),
            "choices": sorted([record_id, choice.value] for record_id, choice in command.choices),
        }
    )


_MEMORY_EFFECT_FAMILIES: Final = frozenset(
    {
        IdentityEffectFamily.RELATIONSHIP_MEMORY,
        IdentityEffectFamily.MEMORY_PROPOSAL,
        IdentityEffectFamily.MEMORY_CONTEXT_LINK,
    }
)

#: The families with actual per-row entity-plane storage, in the order this
#: module walks them. **Not** "the families a split may raise an ambiguity
#: for" -- that question is answered by `dispositions_for`, which is broader
#: than this tuple. **Not**, as of the fix that closed `RI-P2-BLK-001`'s last
#: residual gap, "the families `_post_merge_created` discovers" either -- that
#: is now every family `dispositions_for` admits a disposition for, discovered
#: through three different mechanisms (see `_post_merge_created`). What this
#: tuple answers is narrower and still exactly two questions: which families
#: `EntitiesRepository.records_bound_to_entity_outside` can run its "which of
#: these binds to the survivor" query against, and which families
#: `_bound_records` and the `ASSIGN_TO_ENTITY` execution path
#: (`reparent_entity_reference`) know how to move.
#:
#: **The five whose rows name an entity in a column.** These are exactly
#: `SqlEntityRepository._CHILD_SUBJECTS`, which is not a coincidence: they are
#: the families `records_bound_to_entity_outside` can ask "which of these binds
#: to the survivor" of, and the families `reparent_entity_reference` can move.
#:
#: What that leaves out, and why each is left out rather than forgotten.
#: `ENTITY` and `REVIEW_CASE` and `DERIVED_CONTEXT` admit no disposition at all
#: (see `_DISPOSITIONS_BY_FAMILY`) and so need no entry here either -- an
#: entity's redirect is provable or the split is refused, a review case writes
#: no row, and derived context is recomputed rather than attributed. `PROPOSAL`
#: is excluded on repository truth: `entity_proposals` carries no entity column
#: at all and makes its references inside its payload, so there is nothing for
#: an assignment to rewrite -- and correspondingly `dispositions_for(PROPOSAL)`
#: no longer offers `ASSIGN_TO_ENTITY`, only `LEAVE_UNRESOLVED`. The three
#: memory families are excluded from *this tuple* for the same reason:
#: `RelationshipMemoryRepository` and `RelationshipMemoryProposalRepository`
#: publish no operator-directed rebinding -- the former is read/admit/replay
#: only and the latter is insert-only -- and a memory is "one durable statement
#: about **one** generalized `Entity`" (`docs/specs/relationship-memory-v0.1.md`
#: lines 20-22), so moving one between subjects would need a governed memory
#: operation this plane does not have. That absence of a writer is exactly why
#: `dispositions_for` narrows those three (and `PROPOSAL`) to
#: `LEAVE_UNRESOLVED` only -- `LEAVE_UNRESOLVED` needs no writer, so it remains
#: honest to offer even though `ASSIGN_TO_ENTITY` is not.
#:
#: These four families are **not** in this tuple, and they *do* now raise both
#: `POST_MERGE_MODIFIED` ambiguities (via `dispositions_for`, not via this
#: tuple -- see the gate above this definition) and `POST_MERGE_CREATED`
#: ambiguities (via the two other discovery mechanisms `_post_merge_created`
#: runs beside its walk of this tuple, not via
#: `records_bound_to_entity_outside`). What *stays* scoped to this tuple, and
#: unreachable for the four regardless of discovery, is `ASSIGN_TO_ENTITY`
#: execution (`_bound_records`): it is only ever called for a disposition each
#: family's own `allowed_dispositions` admits, and none of the four admits
#: `ASSIGN_TO_ENTITY`.
_ATTRIBUTABLE_FAMILIES: Final[tuple[IdentityEffectFamily, ...]] = (
    IdentityEffectFamily.ALIAS,
    IdentityEffectFamily.IDENTIFIER,
    IdentityEffectFamily.ASSIGNMENT,
    IdentityEffectFamily.RELATIONSHIP,
    IdentityEffectFamily.OBSERVATION,
)


def _stored_digest_key(
    ambiguity: PreviewAmbiguity,
) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...], Mapping[str, object]]:
    """One persisted ambiguity in the form `ambiguity_digest_for` binds."""
    return (
        ambiguity.record_family.value,
        ambiguity.record_id,
        ambiguity.reason,
        tuple(ambiguity.allowed_dispositions),
        tuple(ambiguity.allowed_target_entity_ids),
        ambiguity.evidence_summary,
    )


def _inverse_drafts(effects: Sequence[IdentityEffect]) -> tuple[IdentityEffectDraft, ...]:
    """The source ledger reversed as content-blind semantic restorations.

    The source effect remains the immutable historical record of the exact
    pre-merge state. A split must not write its old concurrency token back onto
    the canonical row: doing so would create an ABA window in which a command
    read before the merge could succeed after the split. The six version-owned
    families therefore restore every semantic field while advancing from the
    post-merge token.
    """
    versioned = {
        IdentityEffectFamily.ENTITY,
        IdentityEffectFamily.ALIAS,
        IdentityEffectFamily.IDENTIFIER,
        IdentityEffectFamily.ASSIGNMENT,
        IdentityEffectFamily.RELATIONSHIP,
        IdentityEffectFamily.RELATIONSHIP_MEMORY,
    }
    restored_entity_versions = {
        effect.record_id: current_version + 1
        for effect in effects
        if effect.family is IdentityEffectFamily.ENTITY
        and isinstance(current_version := effect.after_state.get("version"), int)
    }

    def restored_state(effect: IdentityEffect) -> Mapping[str, object]:
        restored = dict(effect.before_state)
        if effect.family in versioned:
            current_version = effect.after_state.get("version")
            if not isinstance(current_version, int):
                raise ValueError("a versioned identity effect records its resulting version")
            restored["version"] = current_version + 1
        elif effect.family is IdentityEffectFamily.MEMORY_PROPOSAL:
            before_links = effect.before_state.get("context_links")
            after_links = effect.after_state.get("context_links")
            if not isinstance(before_links, list) or not isinstance(after_links, list):
                raise ValueError("a memory proposal identity effect records its context links")
            if len(before_links) != len(after_links):
                raise ValueError("a memory proposal identity effect preserves its link set")
            restored_links: list[dict[str, object]] = []
            for before_link, after_link in zip(before_links, after_links, strict=True):
                if not isinstance(before_link, dict) or not isinstance(after_link, dict):
                    raise ValueError("a memory proposal identity effect records link objects")
                restored_link = dict(before_link)
                origin = after_link.get("origin_subject_entity_id")
                if origin is not None:
                    restored_link["origin_subject_entity_id"] = origin
                restored_links.append(restored_link)
            restored["context_links"] = restored_links
            original_subject = effect.before_state.get("subject_entity_id")
            if isinstance(original_subject, str) and original_subject in restored_entity_versions:
                restored["expected_subject_version"] = restored_entity_versions[original_subject]
        return restored

    return tuple(
        IdentityEffectDraft(
            family=effect.family,
            record_id=effect.record_id,
            kind=effect.kind,
            before_state=effect.after_state,
            after_state=restored_state(effect),
        )
        for effect in reversed(effects)
    )


def _sequence_split_effects(
    drafts: Sequence[IdentityEffectDraft],
    *,
    identity_operation_id: str,
    principal_id: str,
    recorded_at: datetime,
) -> tuple[IdentityEffect, ...]:
    """Materialize already reverse-ordered split effects without re-sorting them."""
    subjects = [(draft.family, draft.record_id) for draft in drafts]
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
        for sequence, draft in enumerate(drafts, start=1)
    )


def _split_plan_digest(drafts: Sequence[IdentityEffectDraft]) -> str:
    by_family: dict[IdentityEffectFamily, int] = {}
    for draft in drafts:
        by_family[draft.family] = by_family.get(draft.family, 0) + 1
    return plan_digest_for(
        groups=(
            (family.value, FamilyDisposition.TRANSFORMED.value, count)
            for family, count in by_family.items()
        ),
        conflicts=(),
        projected_effects=drafts,
    )


def _split_request_digest(command: SplitCommand) -> str:
    if not command.idempotency_key:
        raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
    return state_digest(
        {
            "operation_type": IdentityOperationType.SPLIT.value,
            "principal_id": command.principal_id,
            "preview_id": command.preview_id,
            "preview_digest": command.preview_digest,
            "reason": command.reason,
            "evidence_refs": sorted(command.evidence_refs),
            # The dispositions are part of what the operator authorised, on
            # `_request_digest`'s argument for a merge's choices. Without them a
            # retry under the same key that settled the same ambiguities
            # differently would be answered with the first attempt's receipt --
            # reporting a split as performed that was never asked for.
            "dispositions": sorted(
                [
                    decision.ambiguity_id,
                    decision.disposition.value,
                    decision.target_entity_id or "",
                ]
                for decision in command.dispositions
            ),
        }
    )
