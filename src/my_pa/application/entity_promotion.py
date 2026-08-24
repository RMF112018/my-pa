"""What an accepted proposal becomes: the canonical command that performs it.

**One rule, and this module exists so that it has somewhere to be true.**
Section 14 of the Phase B contract: an accepted ordinary Entity proposal executes
"through the canonical Phase A mutation services", and Review must not duplicate
mutation logic. The failure that rule guards against is not hypothetical — it is
what `EntityGovernanceService._apply` did until `WP-RI-B-05`, which is that a
review path with its own copy of a mutation ends up with its own copy of the
mutation's *rules*, and the copy is always the weaker one. So nothing here
writes. This module answers one question — which canonical command carries out
this proposal, and with which fields — and the Review path that decided the case
constructs that command and hands it to the service that already owns every
protection it has to inherit: Principal isolation, the expected-version guard,
the active partial uniques, evidence validation, idempotency, the mutation
ledger and the plane's stable errors.

**The field names are the same names, and that is a property rather than a
coincidence.** `domain.relationship.proposal_payload` builds each kind's schema
out of the canonical command that would carry that kind out, so an accepted
payload names only fields that command takes. This module therefore performs no
renaming and holds no per-kind translation table of field names: it converts the
values whose stored form is a string into the members and instants the command's
constructor requires, and passes the rest through. `test_entity_promotion` holds
the property both ways -- every schema field is a field of the mapped command,
and every mapped command is the one whose capability performs that kind -- so a
kind whose schema drifts from its command reddens here rather than at a caller.

**What this module deliberately does not produce.** The expected versions and the
idempotency key are absent from every result. They belong to the moment of
promotion rather than to the proposal: a version read when a proposal was filed
and replayed when a reviewer accepted it days later is a stale-write check that
has stopped checking, and an idempotency key derived from the proposal would make
a reviewer's second, corrected decision replay the first one's receipt. The
Principal is absent for the reason it is absent from every command in this
repository.

**Identity correction is refused rather than routed.** `merge_entities` and
`split_identity` have no canonical command here and must not acquire one:
section 15 makes acceptance of those kinds reviewed intent only, and identity
mutation an operator act under `entity_identity_correction`. A promotion table
that held an entry for them would be a merge endpoint reachable from a review
disposition, which is exactly the shape `EntityGovernanceService` was corrected
away from.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.application.commands import (
    AddEntityAlias,
    BindEntityIdentifier,
    CreateEntity,
    CreateEntityAssignment,
    CreateEntityRelationship,
    EndEntityAssignment,
    EndEntityRelationship,
    ResolveUnresolvedMention,
    RetireEntityAlias,
    RetireEntityIdentifier,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
    UpdateEntity,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AliasType,
    AssignmentType,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import (
    ACCEPTED_PROPOSAL_STATES,
    IDENTITY_CORRECTION_PROPOSAL_KINDS,
    EntityFactEvidenceLink,
    EntityGovernanceError,
    EntityProposal,
    EntityProposalKind,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ResolutionDisposition,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "PromotionCall",
    "PromotionCommand",
    "PromotionError",
    "UnpromotableProposalError",
    "evidence_links_for",
    "promotion_for",
]


#: Every canonical command an accepted ordinary proposal can become.
#:
#: Spelled as a union rather than left as `type[object]` so that a caller
#: destructuring a `PromotionCall` is checked against the fifteen commands that
#: can actually appear in one, and so that a sixteenth added to the table below
#: without being admitted here is a type error rather than a runtime surprise.
type PromotionCommand = (
    CreateEntity
    | UpdateEntity
    | BindEntityIdentifier
    | RetireEntityIdentifier
    | SupersedeEntityIdentifier
    | AddEntityAlias
    | RetireEntityAlias
    | SupersedeEntityAlias
    | CreateEntityAssignment
    | ReviseEntityAssignment
    | EndEntityAssignment
    | CreateEntityRelationship
    | ReviseEntityRelationship
    | EndEntityRelationship
    | ResolveUnresolvedMention
)


class PromotionError(EntityGovernanceError):
    """A proposal was asked what it promotes to and has no answer."""


class UnpromotableProposalError(PromotionError):
    """This proposal names no canonical mutation, or names one nobody accepted.

    Two conditions and one error, because both mean the same thing to the caller
    -- there is nothing to execute -- and telling them apart would require this
    module to explain, to whoever asked, that a merge is performed elsewhere.
    That explanation belongs in the Review path's own refusal, which knows
    whether it is talking to a reviewer or to a producer.
    """


@dataclass(frozen=True, slots=True)
class PromotionCall:
    """The canonical command one accepted proposal promotes to, and its fields.

    Not the command itself, and the difference is the whole reason this type
    exists: the command's constructor requires the expected versions and the
    idempotency key that only the promoting transaction can supply, so a half
    built command would have to be a mutable one. This carries what the proposal
    determines and leaves a hole exactly where the moment of promotion has to
    speak.

    `record_family` is here rather than derived by the caller because it is the
    same fact as `command` read from the ledger's side, and it is what fills
    `EntityProposal.accepted_record_type` once the write returns an identifier.
    """

    kind: EntityProposalKind
    capability: Capability
    command: type[PromotionCommand]
    record_family: MutationRecordFamily
    #: The proposal's own contribution to the command's keyword arguments. Every
    #: name is a field of `command`; the fields absent from it are the ones the
    #: promoting transaction owns.
    fields: Mapping[str, object]


#: Which canonical command carries out each ordinary kind, and which record
#: family it writes.
#:
#: Fifteen entries, and the two absences are load-bearing rather than pending.
#: See the module docstring: `merge_entities` and `split_identity` are refused
#: here so that no reviewer's disposition can reach an identity mutation.
#:
#: The capability is read off each command's own `capability` class variable
#: rather than restated, so this table cannot come to disagree with the command
#: about which capability performs it.
_PROMOTION_BY_KIND: Final[
    Mapping[EntityProposalKind, tuple[type[PromotionCommand], MutationRecordFamily]]
] = MappingProxyType(
    {
        EntityProposalKind.CREATE_ENTITY: (CreateEntity, MutationRecordFamily.ENTITY),
        EntityProposalKind.UPDATE_ENTITY: (UpdateEntity, MutationRecordFamily.ENTITY),
        EntityProposalKind.BIND_IDENTIFIER: (
            BindEntityIdentifier,
            MutationRecordFamily.IDENTIFIER,
        ),
        EntityProposalKind.RETIRE_IDENTIFIER: (
            RetireEntityIdentifier,
            MutationRecordFamily.IDENTIFIER,
        ),
        EntityProposalKind.SUPERSEDE_IDENTIFIER: (
            SupersedeEntityIdentifier,
            MutationRecordFamily.IDENTIFIER,
        ),
        EntityProposalKind.RECORD_ALIAS: (AddEntityAlias, MutationRecordFamily.ALIAS),
        EntityProposalKind.RETIRE_ALIAS: (RetireEntityAlias, MutationRecordFamily.ALIAS),
        EntityProposalKind.SUPERSEDE_ALIAS: (SupersedeEntityAlias, MutationRecordFamily.ALIAS),
        EntityProposalKind.RECORD_ASSIGNMENT: (
            CreateEntityAssignment,
            MutationRecordFamily.ASSIGNMENT,
        ),
        EntityProposalKind.REVISE_ASSIGNMENT: (
            ReviseEntityAssignment,
            MutationRecordFamily.ASSIGNMENT,
        ),
        EntityProposalKind.END_ASSIGNMENT: (EndEntityAssignment, MutationRecordFamily.ASSIGNMENT),
        EntityProposalKind.RECORD_RELATIONSHIP: (
            CreateEntityRelationship,
            MutationRecordFamily.RELATIONSHIP,
        ),
        EntityProposalKind.REVISE_RELATIONSHIP: (
            ReviseEntityRelationship,
            MutationRecordFamily.RELATIONSHIP,
        ),
        EntityProposalKind.END_RELATIONSHIP: (
            EndEntityRelationship,
            MutationRecordFamily.RELATIONSHIP,
        ),
        EntityProposalKind.RESOLVE_MENTION: (
            ResolveUnresolvedMention,
            MutationRecordFamily.OBSERVATION,
        ),
    }
)


def _moment(value: str | bool) -> datetime:
    """One stored ISO-8601 instant as the aware `datetime` its command takes."""
    if not isinstance(value, str):
        raise UnpromotableProposalError("a proposed instant is stored as text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as failure:
        raise UnpromotableProposalError("a proposed instant is ISO-8601") from failure
    return ensure_utc(parsed)


def _flag(value: str | bool) -> bool:
    if not isinstance(value, bool):
        raise UnpromotableProposalError("a proposed flag is stored as a boolean")
    return value


def _member[T: StrEnum](enum: type[T]) -> Callable[[str | bool], T]:
    """A converter from one stored value to one member of `enum`.

    Strict on purpose, and it is `commands._entity_vocabulary`'s own strictness
    read from the other end: a command takes the member and never the string,
    because the wire's string is turned into a member in exactly one place. A
    promotion is that place for a stored payload, and a value the enum does not
    hold is refused here rather than reaching a constructor that would refuse it
    with a message about a request nobody made.
    """

    def convert(value: str | bool) -> T:
        if not isinstance(value, str):
            raise UnpromotableProposalError("a proposed vocabulary member is stored as text")
        try:
            return enum(value)
        except ValueError as failure:
            raise UnpromotableProposalError("a proposed value is outside its vocabulary") from (
                failure
            )

    return convert


#: How each payload field whose stored form is not the command's form converts.
#:
#: Keyed by field *name* and not by kind, because the names are shared: an
#: `effective_from` is the same instant whichever kind proposed it, and a table
#: per kind would be fifteen chances for two of them to disagree. Every name
#: absent from here reaches its command as the string it was stored as, which is
#: what its command's own field takes.
_CONVERSION_BY_FIELD: Final[Mapping[str, Callable[[str | bool], object]]] = MappingProxyType(
    {
        "alias_type": _member(AliasType),
        "assignment_type": _member(AssignmentType),
        "disposition": _member(ResolutionDisposition),
        "effective_end": _moment,
        "effective_from": _moment,
        "effective_to": _moment,
        "end_now": _flag,
        "entity_type": _member(EntityType),
        "namespace": _member(CallerNamespace),
        "relationship_type": _member(EntityRelationshipType),
        "status": _member(EntityStatus),
    }
)


def _verbatim(value: str | bool) -> object:
    """The stored value, unchanged, for every field whose command takes a string."""
    return value


def promotion_for(proposal: EntityProposal) -> PromotionCall:
    """The canonical command this accepted proposal promotes to.

    Refuses anything that is not accepted, because a promotion is the execution
    of a decision and there is no decision to execute otherwise -- and because a
    module that answered for an open proposal would let a caller compute what a
    proposal *would* do and then perform it without deciding it.
    """
    if proposal.state not in ACCEPTED_PROPOSAL_STATES:
        raise UnpromotableProposalError("a proposal is promoted when it has been accepted")
    if proposal.kind in IDENTITY_CORRECTION_PROPOSAL_KINDS:
        raise UnpromotableProposalError("an accepted identity correction promotes nothing")
    command, family = _PROMOTION_BY_KIND[proposal.kind]
    fields = {
        name: _CONVERSION_BY_FIELD.get(name, _verbatim)(value)
        for name, value in proposal.payload.values
    }
    return PromotionCall(
        kind=proposal.kind,
        capability=command.capability,
        command=command,
        record_family=family,
        fields=MappingProxyType(fields),
    )


def evidence_links_for(
    proposal: EntityProposal,
    *,
    principal_id: str,
    record_family: MutationRecordFamily,
    record_id: str,
    at: datetime,
) -> tuple[EntityFactEvidenceLink, ...]:
    """The links that carry a promoted proposal's evidence onto the record it became.

    **Why promotion has to write these at all.** The canonical commands carry an
    `evidence` tuple, but it is a tuple of capture spans -- `_entity_evidence`
    validates every member as an `IdKind.SPAN` -- and a proposal cites entity
    observations. So the evidence a producer offered cannot travel inside the
    command, and a promotion that stopped at the command would leave the promoted
    fact with no link back to what was observed. Section 14: evidence links must
    survive promotion.

    **The authority is `REVIEW_ACCEPTED`, and it is the only honest value.**
    `MutationAuthority` already holds it and defines it as "a review case having
    been dispositioned". `USER_CONFIRMED_ASSERTION` would say the user made the
    assertion, when what the user did was accept somebody else's;
    `SYSTEM_DETERMINISTIC` would say the fact could be recomputed from inputs
    already held, which is exactly the claim a source or model conclusion may not
    make. Nothing is invented here: the third member is the one the vocabulary
    was given for this act.

    The role is `SUPPORTING` rather than `DIRECT`: the observation supports the
    fact a reviewer accepted, and `DIRECT` is what the plane uses for a record
    that *is* the fact stated.

    **The Principal is an argument and is not read off the proposal**, which is
    the rule every write on this plane follows: the owning Principal comes from
    the authenticated context and never from a record or a payload.
    `EntityGovernanceService._preserve_refusal` takes it the same way for the
    same reason, even though its command carries one. The proposal was read from
    one partition and these rows are written into one, and the value that decides
    which is the caller's authenticated identity rather than a field that
    travelled with the data.

    `OBSERVATION` is refused rather than answered with nothing. A
    `resolve_mention` promotion's subject *is* an observation, so a link from it
    to the observations cited for it would be a record pointing at itself; that
    decision's evidence is written by `EntityGovernanceService.resolve_mention`
    onto `entity_resolution_decisions.evidence_link_ids`, where the decision that
    cited it can be read beside it.
    """
    if record_family is MutationRecordFamily.OBSERVATION:
        raise UnpromotableProposalError("this record family carries no promoted evidence link")
    return tuple(
        EntityFactEvidenceLink(
            link_id=issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK),
            principal_id=principal_id,
            role=EvidenceRole.SUPPORTING,
            authority=MutationAuthority.REVIEW_ACCEPTED,
            created_at=at,
            entity_id=record_id if record_family is MutationRecordFamily.ENTITY else None,
            identifier_id=record_id if record_family is MutationRecordFamily.IDENTIFIER else None,
            alias_id=record_id if record_family is MutationRecordFamily.ALIAS else None,
            assignment_id=record_id if record_family is MutationRecordFamily.ASSIGNMENT else None,
            relationship_id=(
                record_id if record_family is MutationRecordFamily.RELATIONSHIP else None
            ),
            entity_observation_id=observation_id,
        )
        for observation_id in proposal.observation_ids
    )
