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

**What blocks, and why blocking is the honest answer.** Relationship Memory
names entities as subjects and `WP-RI-08` owns what a merge does to that
binding; this phase's effect ledger has no family that could record it, so a
merge over an entity a memory names is refused rather than performed with no
way back. An active external identifier the survivor already holds as a former
one is the other, and section 21 settles that one outright. Neither refusal is a
gap being hidden: it is section 20's requirement that an unsupported family
surface an explicit blocker and that apply refuse the case.

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
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.application.errors import (
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import EntitiesRepository, RelationshipMemoryRepository
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
    conflict_digest_for,
    preview_digest_for,
    sequence_effects,
    state_digest,
)
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

    Deliberately **not** `IdentityEffectFamily`, which has nine members and is a
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
class _Analysis:
    """Everything one reading of the world produced."""

    groups: tuple[MergeAffectedGroup, ...]
    conflicts: tuple[IdentityConflict, ...]
    changes: tuple[_RowChange, ...]


#: The reason recorded on a proposal an identity correction closed.
#:
#: A fixed sentence rather than the operator's own words. `invalidated_reason`
#: is a stored column on a record about a person, and section 28 keeps narrative
#: text out of what a merge leaves behind; what a later reader needs from this
#: column is *which* mechanism closed the proposal, and that is the same
#: sentence every time.
INVALIDATED_BY_MERGE = "the entity this proposal names was merged away by a governed correction"


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
                "version": entity.version,
            },
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
        ),
        after_state=_alias_state(
            entity_id=survivor_entity_id,
            state=alias.state.value,
            version=alias.version + 1,
            successor=alias.superseded_by_alias_id,
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
        ),
        after_state=_alias_state(
            entity_id=alias.entity_id,
            state=AliasState.SUPERSEDED.value,
            version=alias.version + 1,
            successor=counterpart_id,
        ),
        expected_version=alias.version,
        coalesced_into=counterpart_id,
    )


def _alias_state(
    *, entity_id: str, state: str, version: int, successor: str | None
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
        ),
        after_state=_identifier_state(
            entity_id=survivor_entity_id,
            state=identifier.state.value,
            version=identifier.version + 1,
            successor=identifier.superseded_by_identifier_id,
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
        ),
        after_state=_identifier_state(
            entity_id=identifier.entity_id,
            state=IdentifierState.SUPERSEDED.value,
            version=identifier.version + 1,
            successor=counterpart_id,
        ),
        expected_version=identifier.version,
        coalesced_into=counterpart_id,
    )


def _identifier_state(
    *, entity_id: str, state: str, version: int, successor: str | None
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
                ),
                after_state=_assignment_state(
                    entity_id=entity_id,
                    scope_entity_id=scope_entity_id,
                    state=assignment.state.value,
                    version=assignment.version + 1,
                    successor=assignment.superseded_by_assignment_id,
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
        ),
        after_state=_assignment_state(
            entity_id=assignment.entity_id,
            scope_entity_id=assignment.scope_entity_id,
            state=AssignmentState.SUPERSEDED.value,
            version=assignment.version + 1,
            successor=counterpart_id,
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
) -> dict[str, object]:
    """One assignment row as the ledger records it. No role, no discipline."""
    return {
        "entity_id": entity_id,
        "scope_entity_id": scope_entity_id,
        "state": state,
        "version": version,
        "superseded_by_assignment_id": successor,
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
    )


def _relationship_state(
    *,
    from_entity_id: str,
    to_entity_id: str,
    scope_entity_id: str | None,
    state: str,
    version: int,
    successor: str | None,
) -> dict[str, object]:
    """One directed edge as the ledger records it. Three endpoints and a state."""
    return {
        "from_entity_id": from_entity_id,
        "to_entity_id": to_entity_id,
        "scope_entity_id": scope_entity_id,
        "state": state,
        "version": version,
        "superseded_by_relationship_id": successor,
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


def plan_proposals(proposals: Sequence[EntityProposal]) -> tuple[_RowChange, ...]:
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
                before_state={"state": proposal.state.value},
                after_state={"state": _INVALIDATED_STATE},
            )
        )
        if proposal.review_case_id is not None:
            changes.append(
                _RowChange(
                    family=IdentityEffectFamily.REVIEW_CASE,
                    record_id=proposal.review_case_id,
                    kind=IdentityEffectKind.DEPENDENT_INVALIDATED,
                    before_state={"state": proposal.state.value},
                    after_state={"state": _INVALIDATED_STATE},
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


def _names_a_merged_entity(proposal: EntityProposal, merged_entity_ids: frozenset[str]) -> bool:
    """Whether one proposal's payload names an entity this merge removes.

    Read over the payload's values rather than over a list of field names that
    happen to hold entity identifiers. The seventeen kinds name an entity under
    `entity_id`, `scope_entity_id`, `from_entity_id`, `to_entity_id`,
    `subject_entity_id`, `retained_entity_id` and `merged_entity_id`, and a
    field list would go stale the first time a kind is added -- silently, and in
    the direction that leaves a proposal open against an identity that is gone.
    Matching on the value cannot: an entity identifier is opaque and globally
    unique, so a payload value equal to one *is* a reference to it.
    """
    return any(value in merged_entity_ids for _, value in proposal.payload.values)


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
            ),
            conflict_digest=conflict_digest_for(analysis.conflicts),
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

        survivor, merged = self._require_current_entities(
            principal_id,
            preview.survivor_entity_id,
            preview.expected_survivor_version,
            preview.merged_away,
        )
        analysis = self._analyse(principal_id, survivor, merged, choices=choices)
        if conflict_digest_for(analysis.conflicts) != preview.conflict_digest:
            # The binding still holds and the world moved anyway. A concurrent
            # identifier claim is the case section 27 names, and it is exactly
            # the one the entity versions cannot see: binding an address writes
            # a child row and advances no entity version. Refusing here is what
            # stops a merge from being the write that bypasses the claim.
            raise ConflictError(SafeDetail.PREVIEW_STALE)
        blockers = tuple(conflict for conflict in analysis.conflicts if conflict.blocks)
        if blockers:
            raise ConflictError(*_blocker_details(blockers))
        required = frozenset(
            conflict.record_id for conflict in analysis.conflicts if not conflict.blocks
        )
        if frozenset(choices) != required:
            raise InvalidRequestError(SafeDetail.IDENTITY_CORRECTION_CONFLICT)

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
            state=IdentityOperationState.IN_PROGRESS,
            started_at=at,
        )
        # Opened before the work for two structural reasons rather than one
        # stylistic one. `UNIQUE (principal_id, idempotency_key)` is what makes
        # two concurrent applies under one key serialise here instead of each
        # performing a whole merge and then discovering the other; and the effect
        # ledger's foreign key means no effect is storable until this row exists.
        self._entities.record_identity_operation(principal_id, opened)
        self._write(
            principal_id,
            analysis.changes,
            preview=preview,
            at=at,
            performed_by=performed_by,
        )
        effects = sequence_effects(
            (change.draft for change in analysis.changes),
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
            state=IdentityOperationState.COMPLETED,
            started_at=opened.started_at,
            completed_at=at,
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
                self._entities.redirect_entity(principal_id, change.record_id, survivor_entity_id)
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
            if proposal.is_open and _names_a_merged_entity(proposal, merged_entity_ids)
        ]
        proposal_changes = plan_proposals(open_proposals)
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

        memory_subjects = self._memories.subject_entity_ids(
            merged_entity_ids, principal_id=principal_id
        )
        conflicts.extend(
            IdentityConflict(
                kind=IdentityConflictKind.UNSUPPORTED_FAMILY,
                family=IdentityEffectFamily.ENTITY,
                record_id=entity_id,
            )
            for entity_id in sorted(memory_subjects)
        )
        # The blocker names the *entity*, never a memory. Section 28 forbids a
        # merge preview from distinguishing restricted memory, and a conflict
        # carrying a memory identifier -- or a count of them -- would be exactly
        # that channel. What the operator needs is that this identity cannot be
        # merged yet, and why.
        groups.append(
            MergeAffectedGroup(
                MergeFamily.RELATIONSHIP_MEMORY,
                FamilyDisposition.BLOCKED if memory_subjects else FamilyDisposition.UNCHANGED,
                len(memory_subjects),
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
        return tuple(command.merged_away)

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
