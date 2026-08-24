"""Entity authoring use cases: what the server decides, and what the caller may.

One service, and its whole job is the line between the two, exactly as
`application.relationship_memory` is for the plane beside it. A transport hands
it what a person could legitimately have chosen -- the kind of thing this is,
what to call it, which address belongs to it, which version they read -- and
this module supplies everything else from authenticated context and policy:

* the owning Principal, from `Authorization` and never from a payload;
* every identifier: the entity's, each alias's, each binding's, the ledger
  event's and every evidence link's;
* the **normalized** canonical name and normalized identifier value, which are
  the columns resolution compares by equality and which a caller may therefore
  never supply directly;
* the entity's version, its default status, its created and updated times, the
  authority the change carries and the actor class that made it;
* the correlation identity and the receipt time.

**The caller cannot widen any of them, and the mechanism is absence rather than
validation.** The transport commands have no `principal_id`, no `version`, no
`authority`, no `superseded_by_entity_id`, no `created_at` and no
`normalized_value` field, so a payload naming one is refused by the command
constructor before this module runs. There is nothing here that reads such a
field and decides to ignore it, because a field that can be sent is a field a
later change can start honouring.

**Normalization is a server act, and that is the whole reason `display_value`
is the field a caller sends.** `normalize_name` is NFKD, combining-mark
removal, punctuation-to-space, whitespace collapse and casefold; a caller that
supplied the normalized form directly could supply one that does not match what
the algorithm would have produced, and a row stored in a form the resolver's
equality predicate cannot match does not merely fail to resolve -- it removes
itself from the candidate set and thereby promotes a *neighbouring* entity from
an ambiguous refusal to a confident wrong answer. So the caller sends what a
source actually wrote, and this module derives the form that is matched on.

**Duplicate resolution is rerun here, inside the caller's transaction, and it
refuses rather than links.** See `EntityAuthoringService.create`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from my_pa.contracts.ports import (
    EntitiesRepository,
    EntityMutationAdmission,
    EntityWriteRequest,
    InitialAlias,
    InitialIdentifier,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.authoring import (
    AmbiguousEntityError,
    CallerNamespace,
    ConflictedIdentifierError,
    EntityWriteOperation,
)
from my_pa.domain.relationship.entity import (
    AliasType,
    EntityStatus,
    EntityType,
    ExternalIdentifierNamespace,
    IdentifierState,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.source.registry import issue_identifier

__all__ = ["EntityAuthoringService", "NamedValue"]


class NamedValue:
    """One caller-supplied name form or address, before the server normalizes it.

    A tiny carrier rather than a tuple, so the two strings a caller sends for an
    alias -- its kind and what a source wrote -- cannot be passed in the wrong
    order at a call site. It is not a dataclass and not in `domain.relationship`,
    because it is a transport-shaped pair on its way to being normalized rather
    than anything this plane stores.
    """

    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value


class EntityAuthoringService:
    """Route each governed entity write to the port that admits it.

    Every method here ends in the same two statements -- build the request, then
    replay-or-admit -- and the difference between them is entirely which fields
    the request carries. That shape is deliberate: the *decision* about what a
    write does to storage belongs to the repository, which holds the guarded
    `UPDATE` and the partial uniques, and a rule restated here could disagree
    with the one the server actually enforces.
    """

    def create(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_type: EntityType,
        display_name: str,
        aliases: Sequence[NamedValue],
        identifiers: Sequence[NamedValue],
        reason: str | None,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Bring one entity into existence, or refuse because one already exists.

        **Duplicate resolution is rerun here rather than trusted from the
        caller, and it is rerun inside the caller's transaction.** A client that
        resolved a name a moment ago resolved it against a snapshot; between
        that read and this write another session can bind the very address this
        create carries. Section 15.2 makes the outcome of that non-negotiable:
        conflicting immutable identifiers prevent an automatic merge, and an
        ambiguous mention remains unresolved rather than being forced into the
        nearest person.

        So two refusals, and **neither of them returns the entity it found**:

        * any supplied external identity that is already some entity's *current*
          identity refuses with `conflicted_identifier`. Linking to that entity
          instead would be a merge performed as a side effect of a create, and
          creating a second claimant is the state the partial unique exists to
          prevent;
        * a canonical name equal to an existing entity's, **when the request
          supplies no external identity at all**, refuses with
          `ambiguous_identity`. A name alone is insufficient evidence in either
          direction: it is not enough to say these are the same person, and it
          is not enough to say they are different ones.

        **The identity clause is what makes a genuine namesake creatable, and it
        is a decision rather than a loophole.** Two real people do share a name.
        A create that refused on name equality with no way past it would make the
        second Sarah Chen unrecordable, which pushes a user into editing the
        first one -- the false join this plane exists to avoid, reached by
        refusing to admit a true fact. Section 15.2 says an exact identifier is
        strong evidence; a request that carries one, and whose identifier is
        held by nobody, has produced exactly that evidence that this is somebody
        else. A request that carries none has produced nothing but the name.

        **No expected version, because there is nothing to have read.** Every
        other write on this plane names one; a create names an idempotency key
        instead, and the key is what makes a retried create return the original
        entity rather than a second one.
        """
        canonical_name = normalize_name(display_name)
        initial_identifiers = tuple(
            InitialIdentifier(
                identifier_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
                namespace=CallerNamespace(named.kind).namespace,
                normalized_value=normalize_identifier(
                    CallerNamespace(named.kind).namespace, named.value
                ),
                display_value=named.value,
            )
            for named in identifiers
        )
        initial_aliases = tuple(
            InitialAlias(
                alias_id=issue_identifier(IdKind.ENTITY_ALIAS),
                alias_type=AliasType(named.kind),
                normalized_value=normalize_name(named.value),
                display_value=named.value,
            )
            for named in aliases
        )
        request = self._request(
            EntityWriteOperation.CREATE,
            capability="entities.create",
            principal_id=principal_id,
            entity_id=None,
            expected_version=None,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            audit_id=audit_id,
            at=at,
            minted_entity_id=issue_identifier(IdKind.ENTITY),
            entity_type=entity_type,
            display_name=display_name,
            canonical_name=canonical_name,
            reason=reason,
            initial_aliases=initial_aliases,
            initial_identifiers=initial_identifiers,
        )
        # **The replay is decided before duplicate resolution, and the order is
        # load-bearing.** A retried create names an entity the first attempt
        # already brought into existence, so running resolution first would find
        # that entity and refuse the retry as ambiguous -- reporting a duplicate
        # to the caller whose own earlier request created it, and doing so
        # forever. The key is what says "this is the same request"; resolution
        # answers a question only a *new* request is asking.
        replayed = repository.mutation_replay_for(
            request.idempotency_key,
            request.payload_digest,
            principal_id=request.principal_id,
            capability=request.capability,
        )
        if replayed is not None:
            return EntityMutationAdmission(receipt=replayed, created=False)
        self._refuse_a_duplicate(
            repository,
            principal_id=principal_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            identifiers=initial_identifiers,
        )
        return repository.admit_mutation(request)

    def update(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        display_name: str | None,
        canonical_name: str | None,
        status: EntityStatus | None,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Correct what one entity says about itself.

        **`display_name` and `canonical_name` move independently, and the
        asymmetry is the point.** A display-name correction is cosmetic --
        capitalisation, a middle initial, a title -- and changing what
        resolution matches on because somebody fixed a capital letter would
        silently re-point every future lookup. A canonical-name correction *is*
        the matching form, so it is stated separately and it leaves a
        `former_name` alias behind: the old form has to keep resolving, because
        a message sent under it is still a message from this person. The
        repository writes that alias, not this module, because the "unless
        already equivalent" half of the rule is a question about rows.

        The caller still sends a *display* string for `canonical_name`; this
        normalizes it. There is no field in which a caller could supply the
        matched form directly, for the reason the module docstring gives.

        `reason` is required here and optional on a create, and the difference
        is what each act destroys. A create adds a record and explains itself;
        an update replaces what the plane previously asserted about a person,
        and an unexplained replacement is the row a later reader cannot
        reconstruct.
        """
        return self._admit(
            repository,
            self._request(
                EntityWriteOperation.UPDATE,
                capability="entities.update",
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                display_name=display_name,
                canonical_name=None if canonical_name is None else normalize_name(canonical_name),
                status=status,
                reason=reason,
                # Minted whether or not a former-name alias turns out to be
                # needed, because the repository decides that from rows this
                # layer has not read and an identifier cannot be minted inside
                # the statement that needs it.
                minted_child_id=issue_identifier(IdKind.ENTITY_ALIAS),
            ),
        )

    def archive(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Withdraw one entity from current use. Reversible, and not a delete."""
        return self._transition(
            repository,
            EntityWriteOperation.ARCHIVE,
            capability="entities.archive",
            principal_id=principal_id,
            entity_id=entity_id,
            expected_version=expected_version,
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            audit_id=audit_id,
            at=at,
        )

    def restore(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Return one archived entity to the status it was archived from.

        The status it comes back as is `archived_from_status`, which the archive
        recorded. Nothing here guesses `active`: an entity that was `historical`
        before somebody archived it would come back claiming to be current,
        which is a false fact about a person produced by a bookkeeping
        operation.
        """
        return self._transition(
            repository,
            EntityWriteOperation.RESTORE,
            capability="entities.restore",
            principal_id=principal_id,
            entity_id=entity_id,
            expected_version=expected_version,
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            audit_id=audit_id,
            at=at,
        )

    def bind_identifier(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        namespace: CallerNamespace,
        display_value: str,
        effective_from: datetime | None,
        effective_to: datetime | None,
        evidence: Sequence[str],
        reason: str | None,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Record one external address as this entity's current identity.

        `expected_version` is the **entity's**, not a binding's, because a
        binding changes what the entity says about itself and the entity is the
        aggregate. A caller that bound one address and then tried to bind a
        second using the version it read before the first is refused, which is
        the point.

        An address that is currently a different entity's refuses with
        `conflicted_identifier` and is never transferred. An address this entity
        already holds refuses with `duplicate_fact` rather than succeeding
        silently: the unguarded `EntitiesRepository.bind_identifier` treats that
        as a no-op, which is right for a resolution path that binds what it
        finds, and wrong for a governed write that would otherwise hand back a
        receipt for a binding it did not make.
        """
        return self._admit(
            repository,
            self._request(
                EntityWriteOperation.BIND_IDENTIFIER,
                capability="entities.identifiers.bind",
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                minted_child_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
                namespace=namespace.namespace,
                normalized_value=normalize_identifier(namespace.namespace, display_value),
                display_value=display_value,
                effective_from=effective_from,
                effective_to=effective_to,
                reason=reason,
                evidence=tuple(evidence),
            ),
        )

    def retire_identifier(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        identifier_id: str,
        expected_identifier_version: int,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Record that one binding no longer holds, keeping the row that resolves it.

        Retired rather than deleted, and the difference is a message from four
        years ago: the address the sender used then still has to resolve to the
        person who used it. A retired row sits outside the active partial
        unique, so the same address may later be reissued to somebody else
        without the history being destroyed to make room for it.

        There is no successor to name here. A binding that was *corrected* is
        superseded and names what replaced it; one that merely stopped being
        true is retired, and pointing at nothing is the honest answer.
        """
        return self._admit(
            repository,
            self._request(
                EntityWriteOperation.RETIRE_IDENTIFIER,
                capability="entities.identifiers.retire",
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                target_child_id=identifier_id,
                target_child_version=expected_identifier_version,
                reason=reason,
            ),
        )

    def supersede_identifier(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        identifier_id: str,
        expected_identifier_version: int,
        namespace: CallerNamespace,
        display_value: str,
        effective_from: datetime | None,
        effective_to: datetime | None,
        evidence: Sequence[str],
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Replace one binding with another, atomically, and say which replaced which.

        One capability rather than a retire followed by a bind, because the two
        halves must not be separable. Between them the entity would hold no
        current address at all, and a reader arriving in that window would see a
        person whose mail resolves to nobody. The replacement is written and the
        old row is pointed at it inside one statement pair; either both land or
        neither does.
        """
        return self._admit(
            repository,
            self._request(
                EntityWriteOperation.SUPERSEDE_IDENTIFIER,
                capability="entities.identifiers.supersede",
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                minted_child_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
                target_child_id=identifier_id,
                target_child_version=expected_identifier_version,
                namespace=namespace.namespace,
                normalized_value=normalize_identifier(namespace.namespace, display_value),
                display_value=display_value,
                effective_from=effective_from,
                effective_to=effective_to,
                reason=reason,
                evidence=tuple(evidence),
            ),
        )

    def add_alias(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        alias_type: AliasType,
        display_value: str,
        effective_from: datetime | None,
        effective_to: datetime | None,
        evidence: Sequence[str],
        reason: str | None,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Record one more name form this entity is referred to by.

        **A name another entity already carries is not a conflict and is never
        refused as one.** Two real people do share a name; a plane that treated
        that as a collision would force one of them into the other, which is the
        false join it exists to avoid. What is refused is this entity carrying
        the same name form twice under one alias type, which is a duplicate
        rather than a fact.
        """
        return self._admit(
            repository,
            self._request(
                EntityWriteOperation.ADD_ALIAS,
                capability="entities.aliases.add",
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                minted_child_id=issue_identifier(IdKind.ENTITY_ALIAS),
                alias_type=alias_type,
                normalized_value=normalize_name(display_value),
                display_value=display_value,
                effective_from=effective_from,
                effective_to=effective_to,
                reason=reason,
                evidence=tuple(evidence),
            ),
        )

    def retire_alias(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        alias_id: str,
        expected_alias_version: int,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Record that one name form is no longer used, keeping it matchable."""
        return self._admit(
            repository,
            self._request(
                EntityWriteOperation.RETIRE_ALIAS,
                capability="entities.aliases.retire",
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                target_child_id=alias_id,
                target_child_version=expected_alias_version,
                reason=reason,
            ),
        )

    def supersede_alias(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        alias_id: str,
        expected_alias_version: int,
        alias_type: AliasType,
        display_value: str,
        effective_from: datetime | None,
        effective_to: datetime | None,
        evidence: Sequence[str],
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        """Correct one recorded name form, and say which correction replaced which."""
        return self._admit(
            repository,
            self._request(
                EntityWriteOperation.SUPERSEDE_ALIAS,
                capability="entities.aliases.supersede",
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                minted_child_id=issue_identifier(IdKind.ENTITY_ALIAS),
                target_child_id=alias_id,
                target_child_version=expected_alias_version,
                alias_type=alias_type,
                normalized_value=normalize_name(display_value),
                display_value=display_value,
                effective_from=effective_from,
                effective_to=effective_to,
                reason=reason,
                evidence=tuple(evidence),
            ),
        )

    # ---- the one write path ----------------------------------------------

    def _transition(
        self,
        repository: EntitiesRepository,
        operation: EntityWriteOperation,
        *,
        capability: str,
        principal_id: str,
        entity_id: str,
        expected_version: int,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
    ) -> EntityMutationAdmission:
        return self._admit(
            repository,
            self._request(
                operation,
                capability=capability,
                principal_id=principal_id,
                entity_id=entity_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                audit_id=audit_id,
                at=at,
                reason=reason,
            ),
        )

    def _request(
        self,
        operation: EntityWriteOperation,
        *,
        capability: str,
        principal_id: str,
        entity_id: str | None,
        expected_version: int | None,
        idempotency_key: str,
        correlation_id: str,
        audit_id: str,
        at: datetime,
        minted_entity_id: str | None = None,
        minted_child_id: str | None = None,
        entity_type: EntityType | None = None,
        display_name: str | None = None,
        canonical_name: str | None = None,
        status: EntityStatus | None = None,
        target_child_id: str | None = None,
        target_child_version: int | None = None,
        namespace: ExternalIdentifierNamespace | None = None,
        alias_type: AliasType | None = None,
        normalized_value: str | None = None,
        display_value: str | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
        reason: str | None = None,
        evidence: tuple[str, ...] = (),
        initial_aliases: tuple[InitialAlias, ...] = (),
        initial_identifiers: tuple[InitialIdentifier, ...] = (),
    ) -> EntityWriteRequest:
        """The one place a request's server-owned fields are decided.

        Every identifier this write needs is minted before the request exists,
        because the rows are mutually dependent -- a superseded binding points
        at its replacement, so the replacement's identifier has to exist before
        either row is inserted -- and because a digest computed over minted
        values would make every retry a new key.
        """
        return EntityWriteRequest(
            operation=operation,
            capability=capability,
            principal_id=principal_id,
            correlation_id=correlation_id,
            audit_id=audit_id,
            idempotency_key=idempotency_key,
            server_received_at=at,
            event_id=issue_identifier(IdKind.ENTITY_MUTATION_EVENT),
            entity_id=entity_id,
            expected_version=expected_version,
            minted_entity_id=minted_entity_id,
            minted_child_id=minted_child_id,
            entity_type=entity_type,
            display_name=display_name,
            canonical_name=canonical_name,
            status=status,
            target_child_id=target_child_id,
            target_child_version=target_child_version,
            namespace=namespace,
            alias_type=alias_type,
            normalized_value=normalized_value,
            display_value=display_value,
            effective_from=effective_from,
            effective_to=effective_to,
            reason=reason,
            evidence=evidence,
            initial_aliases=initial_aliases,
            initial_identifiers=initial_identifiers,
            minted_evidence_link_ids=tuple(
                issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK) for _ in evidence
            ),
        )

    def _admit(
        self, repository: EntitiesRepository, request: EntityWriteRequest
    ) -> EntityMutationAdmission:
        """Replay first, then write. The shape `RelationshipMemoryService._admit` uses.

        The pre-read is an optimisation and never the decision: `admit_mutation`
        still relies on `one_entity_mutation_per_key_and_capability`, so two
        concurrent writers that both read `None` still produce one mutation.
        """
        replayed = repository.mutation_replay_for(
            request.idempotency_key,
            request.payload_digest,
            principal_id=request.principal_id,
            capability=request.capability,
        )
        if replayed is not None:
            return EntityMutationAdmission(receipt=replayed, created=False)
        return repository.admit_mutation(request)

    def _refuse_a_duplicate(
        self,
        repository: EntitiesRepository,
        *,
        principal_id: str,
        canonical_name: str,
        entity_type: EntityType,
        identifiers: tuple[InitialIdentifier, ...],
    ) -> None:
        """Rerun duplicate resolution, and refuse rather than choose. See `create`."""
        for identifier in identifiers:
            held = repository.entities_by_identifier(
                principal_id, identifier.namespace, identifier.normalized_value
            )
            if any(binding.state is IdentifierState.ACTIVE for _, binding in held):
                raise ConflictedIdentifierError(
                    "an active external identity binds exactly one entity"
                )
        if identifiers:
            return
        # `entities_by_canonical_name` is an equality read over the matched
        # form, which is the same predicate resolution uses. `search`'s substring
        # match is deliberately not used: a create refused because somebody
        # else's name contains this one would be unusable, and a substring is
        # evidence of nothing about identity.
        same_name = [
            entity
            for entity in repository.entities_by_canonical_name(principal_id, canonical_name)
            if entity.entity_type is entity_type
            and entity.status
            in (EntityStatus.ACTIVE, EntityStatus.INACTIVE, EntityStatus.HISTORICAL)
        ]
        if same_name:
            raise AmbiguousEntityError("a create names an entity that may already exist")
