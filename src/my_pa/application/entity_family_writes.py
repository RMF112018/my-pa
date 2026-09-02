"""The record families' writes, and the ledger row that accounts for each one.

`RI-ENT-WP-08` gave the five Entity-bound record families -- typed names,
addresses, communication methods, project participations and person/organization
affiliations -- a writer in `application.entity_record_families`, and that
service does exactly what it says: it writes the row. It returns
`RecordedFact`/`CorrectedFact`/`RetiredFact`, it appends no
`entity_mutation_events` row, and it holds no idempotency key. Nothing was wrong
with that; a family writer is not a ledger.

`RI-ENT-WP-11` publishes one capability per verb reaching those writers from a
transport, and a capability that reaches a transport needs both of the things
the family writer does not have: a mutation-ledger row, so a change to somebody's
recorded contact details is accountable in the same place every other change to
this plane is, and an idempotency key, so a caller whose response was lost
retries instead of writing twice. This module is where the two are supplied.

**It is a new module rather than an edit to `entity_record_families`, and the
separation is the design.** That file is `RI-ENT-WP-08`'s and is under
independent review on another branch; the alternative -- making the five
families reach `SqlEntitiesRepository._append_mutation` -- would mean changing
around fifteen accepted `EntitiesRepository` port methods from `-> None` to
`-> DirectedReceipt` and giving each an idempotency key and a payload digest,
which is a redesign of an accepted contract rather than a use of one. What this
module uses instead is already there and already generic:
`EntitiesRepository.directed_replay` and
`EntitiesRepository.record_mutation_event` are family-agnostic by construction
-- the first filters on `(principal_id, capability, idempotency_key)` and has no
`record_family` predicate at all, and `entity_mutation_events` carries no
family-specific column and no foreign key on `record_id`.

**What the caller may state, and what only the server may.** Shaped on
`EntityDirectedService`, and the mechanism is the same one: absence. The command
dataclasses in `application.commands` have no `principal_id`, `authority`,
`actor_class`, `state`, `version`, `recorded_at`, `updated_at`, `retired_at` or
`superseded_by_*` field, so a payload naming one is refused by the generated
schema before this module runs. Nothing here reads such a field and decides to
ignore it, because a field that can be sent is a field a later change can start
honouring. The owning Principal comes from the `Authorization`; the authority
and actor class default to `user_confirmed_assertion`/`user` and no transport
command can reach either; every minted identifier belongs to the repository or
to the family writer.

**Atomicity: two statements, not one, and the difference is real.** The directed
plane writes its record and its ledger row inside a single repository method, so
the unique `one_entity_mutation_per_key_and_capability` arbitrates the whole act:
two concurrent writers holding one key produce one row and one typed refusal. Here
the family write and the ledger insert are two separate calls, so that unique
arbitrates only because **the caller owns the transaction** -- `SqlUnitOfWork.entities`
hands out a repository bound to the open transaction, and `ApplicationService.invoke`
is what opens and commits it. Inside a transaction the outcome is still correct:
two concurrent writers with one key both write a family row, exactly one commits
the ledger row, and the loser's whole transaction aborts and takes its family row
with it. **Called outside a transaction, a family row can be left with no ledger
row.** That is a real difference from the directed plane and it is stated here
rather than described as equivalent.

**The refusal a concurrent duplicate produces is also not identical.**
`_append_mutation` wraps its INSERT in `_duplicate_translated(_MUTATION_KEY_UNIQUE)`,
so a key collision at the index becomes a typed `DirectedWriteError`.
`record_mutation_event` does its own pre-read and raises
`EntityMutationConflictError` when the key is held for a *different* request, but
two writers that both passed that pre-read reach the INSERT and the loser gets
the driver's own `IntegrityError`. `SqlEntityRepository.record_mutation_event`
now wraps that INSERT in the same `_duplicate_translated(_MUTATION_KEY_UNIQUE)`
the directed writer uses, so the two writers of one table classify one
constraint one way; `ApplicationService._record_family_translated` is where both
refusals become the public `conflict` a caller reads.

**Nothing here recomputes a rule the schema, the domain or the family writer
already states.** The active partial uniques live in the DDL, the field
invariants live in each domain record's `__post_init__`, the version guard lives
in the repository's guarded `UPDATE`, and the vocabularies live in the domain --
so a second copy here could only disagree with them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from my_pa.application import entity_record_families as record_families
from my_pa.application.commands import (
    AddEntityAddress,
    AddEntityCommunicationMethod,
    AddEntityName,
    RetireEntityAddress,
    RetireEntityCommunicationMethod,
    RetireEntityName,
    ReviseEntityAddress,
    ReviseEntityCommunicationMethod,
    SupersedeEntityName,
)

# `_directed_digest` rather than a second canonicalisation, on the argument that
# function's own docstring makes: what makes a replay decidable is that the same
# material fields hash the same way, and two copies of a canonical form are two
# things that can start disagreeing about key order or separators. Importing a
# module-private helper to keep one copy of a shared rule is the shape
# `infrastructure.persistence.continuity_authoring` already uses for
# `_append_lifecycle_event`.
from my_pa.contracts.ports import (
    DirectedReceipt,
    EntitiesRepository,
    _directed_digest,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.entity import (
    EntityAddressState,
    EntityCommunicationMethodState,
    EntityNameState,
)
from my_pa.domain.relationship.governance import (
    DEFAULT_MUTATION_ACTOR_CLASS,
    DEFAULT_MUTATION_AUTHORITY,
    ActorClass,
    EntityMutationEvent,
    MutationAuthority,
    MutationRecordFamily,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = ["EntityFamilyWriteService"]


def _moment(value: datetime | None) -> str | None:
    """One caller-supplied time in the canonical form the digest hashes.

    `.isoformat()`, which is what `contracts.ports._moment` does for the directed
    requests, so a time that decides a replay is spelled one way on both planes.
    """
    return None if value is None else value.isoformat()


class EntityFamilyWriteService:
    """Route each record-family command to its writer, and account for the write.

    Five steps and one shape, per verb:

    1. Build the **canonical request payload**: an explicit dict of the fields
       the caller supplied and nothing else. Written out per verb rather than
       harvested from the dataclass, because a digest derived from whatever
       fields a command happens to declare would change meaning the next time
       somebody adds one -- and a change of digest is a change of what counts as
       a replay. Deliberately excluded, and for the reasons
       `AssignmentWriteRequest.payload_digest` excludes the same things: the
       correlation identifier, the audit identifier and the receipt time, which
       differ on every attempt by construction and would make every retry a
       conflict; and `authority`/`actor_class`, which the server chooses from
       which path is executing and which would therefore make one key mean
       different things to different callers. The minted record identifier is
       not in it either -- on a create it does not exist yet.
    2. **Replay pre-read** through `directed_replay`. It is an optimisation and
       never the decision, exactly as `EntityDirectedService._replay` says of its
       own: `entity_mutation_events` carries
       `UNIQUE (principal_id, capability, idempotency_key)`, so two concurrent
       writers that both read `None` still produce one ledger row and one
       refusal. It returns the receipt this key already has, or `None`, and
       raises `DirectedWriteError` when the key is bound to a different request.
       A receipt means the write already happened: it is returned and **nothing
       is written**.
    3. Call the `EntityRecordFamilyService` verb.
    4. Append the ledger row through `record_mutation_event`.
    5. Answer with the `DirectedReceipt` shape every mutation on this plane
       answers with.

    **The versions on the receipt are derived from what actually happened, not
    guessed.** An addition is a new row at version 1 with no prior version. A
    supersession mints a *successor*, which is also a brand-new row at version 1,
    so `prior_version` is `None` -- `a_mutation_advances_the_version_it_names`
    requires `new_version > prior_version` and the successor never stood at the
    predecessor's version. What the caller asserted about the predecessor is
    recorded truthfully in `before_state` instead, because the write only
    succeeded against exactly that row at exactly that version. A retirement is
    the one verb that advances a version in place: the guarded `UPDATE` sets
    `version = version + 1` under `WHERE version = expected_version`, so
    `prior_version` is what the caller asserted and `new_version` is one more.
    """

    def __init__(self, families: record_families.EntityRecordFamilyService | None = None) -> None:
        """Hold the family writer, or compose the default one.

        Injectable for the reason `ApplicationService` composes its other
        services: a caller with its own instance passes it, and nothing here
        reaches for a global.
        """
        self._families = families or record_families.EntityRecordFamilyService()

    # --- entity_names ------------------------------------------------------

    def add_name(
        self,
        repository: EntitiesRepository,
        command: AddEntityName,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Record one typed name form, or return the receipt this key already has."""
        payload = {
            "entity_id": command.entity_id,
            "name_type_code": command.name_type_code.value,
            "display_value": command.display_value,
            "is_preferred": command.is_preferred,
            "effective_from": _moment(command.effective_from),
            "effective_to": _moment(command.effective_to),
        }
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_NAMES_ADD.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        recorded = self._families.record_name(
            repository,
            record_families.RecordEntityName(
                entity_id=command.entity_id,
                display_value=command.display_value,
                name_type_code=command.name_type_code,
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
            ),
            principal_id=principal_id,
            at=at,
            authority=authority,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_NAMES_ADD,
            family=MutationRecordFamily.NAME,
            record_id=recorded.record_id,
            prior_version=None,
            new_version=1,
            state=EntityNameState.ACTIVE.value,
            before_state=None,
            superseded_id=None,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    def supersede_name(
        self,
        repository: EntitiesRepository,
        command: SupersedeEntityName,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Supersede one recorded name with its corrected successor.

        A supersession and never an edit: the successor is a new row and the
        predecessor is marked SUPERSEDED pointing at it, so both remain readable.
        The receipt names the successor, because that is the row this write
        created and the row a caller will read next.
        """
        payload = {
            "entity_name_id": command.entity_name_id,
            "expected_version": command.expected_version,
            "entity_id": command.entity_id,
            "name_type_code": command.name_type_code.value,
            "display_value": command.display_value,
            "is_preferred": command.is_preferred,
            "effective_from": _moment(command.effective_from),
            "effective_to": _moment(command.effective_to),
        }
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_NAMES_SUPERSEDE.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        corrected = self._families.correct_name(
            repository,
            record_families.CorrectEntityName(
                entity_name_id=command.entity_name_id,
                expected_version=command.expected_version,
                entity_id=command.entity_id,
                display_value=command.display_value,
                name_type_code=command.name_type_code,
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
            ),
            principal_id=principal_id,
            at=at,
            authority=authority,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_NAMES_SUPERSEDE,
            family=MutationRecordFamily.NAME,
            record_id=corrected.record_id,
            prior_version=None,
            new_version=1,
            state=EntityNameState.ACTIVE.value,
            before_state=_predecessor(corrected.superseded_record_id, command.expected_version),
            superseded_id=corrected.superseded_record_id,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    def retire_name(
        self,
        repository: EntitiesRepository,
        command: RetireEntityName,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Withdraw one recorded name from service, keeping the row and its history."""
        payload = {
            "entity_name_id": command.entity_name_id,
            "expected_version": command.expected_version,
        }
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_NAMES_RETIRE.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        retired = self._families.retire_name(
            repository,
            record_families.RetireEntityName(
                entity_name_id=command.entity_name_id,
                expected_version=command.expected_version,
            ),
            principal_id=principal_id,
            at=at,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_NAMES_RETIRE,
            family=MutationRecordFamily.NAME,
            record_id=retired.record_id,
            prior_version=command.expected_version,
            new_version=command.expected_version + 1,
            state=EntityNameState.RETIRED.value,
            before_state={"state": EntityNameState.ACTIVE.value},
            superseded_id=None,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    # --- entity_addresses --------------------------------------------------

    def add_address(
        self,
        repository: EntitiesRepository,
        command: AddEntityAddress,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Record one typed address, or return the receipt this key already has."""
        payload = _address_payload(command)
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_ADDRESSES_ADD.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        recorded = self._families.record_address(
            repository,
            record_families.RecordEntityAddress(
                entity_id=command.entity_id,
                address_type_code=command.address_type_code,
                raw_value=command.raw_value,
                line1=command.line1,
                line2=command.line2,
                city=command.city,
                region=command.region,
                postal_code=command.postal_code,
                country=command.country,
                label=command.label,
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
            ),
            principal_id=principal_id,
            at=at,
            authority=authority,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_ADDRESSES_ADD,
            family=MutationRecordFamily.ADDRESS,
            record_id=recorded.record_id,
            prior_version=None,
            new_version=1,
            state=EntityAddressState.ACTIVE.value,
            before_state=None,
            superseded_id=None,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    def revise_address(
        self,
        repository: EntitiesRepository,
        command: ReviseEntityAddress,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Supersede one recorded address with its corrected successor.

        `revise` is the audit's spelling for this family and `supersede` is its
        spelling for names; the act is the same one, and it is a supersession
        rather than an edit in both.
        """
        payload = {
            "entity_address_id": command.entity_address_id,
            "expected_version": command.expected_version,
            **_address_payload(command),
        }
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_ADDRESSES_REVISE.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        corrected = self._families.correct_address(
            repository,
            record_families.CorrectEntityAddress(
                entity_address_id=command.entity_address_id,
                expected_version=command.expected_version,
                entity_id=command.entity_id,
                address_type_code=command.address_type_code,
                raw_value=command.raw_value,
                line1=command.line1,
                line2=command.line2,
                city=command.city,
                region=command.region,
                postal_code=command.postal_code,
                country=command.country,
                label=command.label,
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
            ),
            principal_id=principal_id,
            at=at,
            authority=authority,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_ADDRESSES_REVISE,
            family=MutationRecordFamily.ADDRESS,
            record_id=corrected.record_id,
            prior_version=None,
            new_version=1,
            state=EntityAddressState.ACTIVE.value,
            before_state=_predecessor(corrected.superseded_record_id, command.expected_version),
            superseded_id=corrected.superseded_record_id,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    def retire_address(
        self,
        repository: EntitiesRepository,
        command: RetireEntityAddress,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Withdraw one recorded address, keeping the row and releasing its slot."""
        payload = {
            "entity_address_id": command.entity_address_id,
            "expected_version": command.expected_version,
        }
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_ADDRESSES_RETIRE.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        retired = self._families.retire_address(
            repository,
            record_families.RetireEntityAddress(
                entity_address_id=command.entity_address_id,
                expected_version=command.expected_version,
            ),
            principal_id=principal_id,
            at=at,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_ADDRESSES_RETIRE,
            family=MutationRecordFamily.ADDRESS,
            record_id=retired.record_id,
            prior_version=command.expected_version,
            new_version=command.expected_version + 1,
            state=EntityAddressState.RETIRED.value,
            before_state={"state": EntityAddressState.ACTIVE.value},
            superseded_id=None,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    # --- entity_communication_methods --------------------------------------

    def add_communication_method(
        self,
        repository: EntitiesRepository,
        command: AddEntityCommunicationMethod,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Record one contact channel, or return the receipt this key already has."""
        payload = _communication_payload(command)
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_COMMUNICATION_ADD.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        recorded = self._families.record_communication_method(
            repository,
            record_families.RecordCommunicationMethod(
                entity_id=command.entity_id,
                method_type_code=command.method_type_code,
                usage_context_code=command.usage_context_code,
                display_value=command.display_value,
                verification_status_code=command.verification_status_code,
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                linked_external_identifier_id=command.linked_external_identifier_id,
            ),
            principal_id=principal_id,
            at=at,
            authority=authority,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_COMMUNICATION_ADD,
            family=MutationRecordFamily.COMMUNICATION_METHOD,
            record_id=recorded.record_id,
            prior_version=None,
            new_version=1,
            state=EntityCommunicationMethodState.ACTIVE.value,
            before_state=None,
            superseded_id=None,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    def revise_communication_method(
        self,
        repository: EntitiesRepository,
        command: ReviseEntityCommunicationMethod,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Supersede one contact channel with its corrected successor.

        `revise` is the audit's spelling for this family and `supersede` is its
        spelling for names; the act is the same one, and it is a supersession
        rather than an edit in both.
        """
        payload = {
            "communication_method_id": command.communication_method_id,
            "expected_version": command.expected_version,
            **_communication_payload(command),
        }
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_COMMUNICATION_REVISE.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        corrected = self._families.correct_communication_method(
            repository,
            record_families.CorrectCommunicationMethod(
                communication_method_id=command.communication_method_id,
                expected_version=command.expected_version,
                entity_id=command.entity_id,
                method_type_code=command.method_type_code,
                usage_context_code=command.usage_context_code,
                display_value=command.display_value,
                verification_status_code=command.verification_status_code,
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                linked_external_identifier_id=command.linked_external_identifier_id,
            ),
            principal_id=principal_id,
            at=at,
            authority=authority,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_COMMUNICATION_REVISE,
            family=MutationRecordFamily.COMMUNICATION_METHOD,
            record_id=corrected.record_id,
            prior_version=None,
            new_version=1,
            state=EntityCommunicationMethodState.ACTIVE.value,
            before_state=_predecessor(corrected.superseded_record_id, command.expected_version),
            superseded_id=corrected.superseded_record_id,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    def retire_communication_method(
        self,
        repository: EntitiesRepository,
        command: RetireEntityCommunicationMethod,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Withdraw one contact channel, keeping the row and releasing its slot."""
        payload = {
            "communication_method_id": command.communication_method_id,
            "expected_version": command.expected_version,
        }
        digest = _directed_digest(payload)
        replayed = repository.directed_replay(
            Capability.ENTITIES_COMMUNICATION_RETIRE.value,
            command.idempotency_key,
            digest,
            principal_id=principal_id,
        )
        if replayed is not None:
            return replayed
        retired = self._families.retire_communication_method(
            repository,
            record_families.RetireCommunicationMethod(
                communication_method_id=command.communication_method_id,
                expected_version=command.expected_version,
            ),
            principal_id=principal_id,
            at=at,
        )
        return self._account_for(
            repository,
            capability=Capability.ENTITIES_COMMUNICATION_RETIRE,
            family=MutationRecordFamily.COMMUNICATION_METHOD,
            record_id=retired.record_id,
            prior_version=command.expected_version,
            new_version=command.expected_version + 1,
            state=EntityCommunicationMethodState.RETIRED.value,
            before_state={"state": EntityCommunicationMethodState.ACTIVE.value},
            superseded_id=None,
            digest=digest,
            idempotency_key=command.idempotency_key,
            principal_id=principal_id,
            audit_id=audit_id,
            at=at,
            authority=authority,
            actor_class=actor_class,
        )

    # --- the ledger row every verb above leaves behind ----------------------

    def _account_for(
        self,
        repository: EntitiesRepository,
        *,
        capability: Capability,
        family: MutationRecordFamily,
        record_id: str,
        prior_version: int | None,
        new_version: int,
        state: str,
        before_state: dict[str, Any] | None,
        superseded_id: str | None,
        digest: str,
        idempotency_key: str,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority,
        actor_class: ActorClass,
    ) -> DirectedReceipt:
        """Append the ledger row and answer with the receipt it is.

        **The ledger row is the receipt on this plane**, exactly as it is for the
        directed writes: it carries the digest, the key, the before and after
        state and the audit identifier, so re-reading it answers every question a
        separate receipt record would. `receipt_id` is left null for the same
        reason `_append_mutation` leaves it null -- that column exists for a
        receipt store this Phase does not build, and writing the event's own
        identifier into it would be a self-reference dressed as a reference.

        **`before_state` and `after_state` carry identifiers, closed vocabulary
        members and versions, and never a recorded value.** No display value, no
        address, no phone number, no job title. `EntityMutationEvent`'s own
        docstring states the rule and this is one of the writers it is about:
        this ledger is read by operators, exported, and rendered in failures, and
        a photograph of a name row taken wholesale is exactly how somebody's name
        would arrive on all three surfaces.

        `replayed=False` unconditionally. Reaching here means step 2 found no
        prior receipt and the write was performed, and a replay returns before
        this method is called.
        """
        event_id = issue_identifier(IdKind.ENTITY_MUTATION_EVENT)
        repository.record_mutation_event(
            principal_id,
            EntityMutationEvent(
                event_id=event_id,
                principal_id=principal_id,
                capability=capability.value,
                record_family=family,
                record_id=record_id,
                prior_version=prior_version,
                new_version=new_version,
                authority=authority,
                actor_class=actor_class,
                idempotency_key=idempotency_key,
                request_digest=digest,
                correlation_id=issue_identifier(IdKind.CORRELATION),
                audit_id=audit_id,
                recorded_at=at,
                before_state=before_state,
                after_state={"state": state},
            ),
        )
        return DirectedReceipt(
            mutation_event_id=event_id,
            record_id=record_id,
            record_family=family,
            prior_version=prior_version,
            version=new_version,
            state=state,
            audit_id=audit_id,
            idempotency_key=idempotency_key,
            superseded_id=superseded_id,
            evidence_refs=(),
            issued_at=at,
            replayed=False,
        )


def _address_payload(command: AddEntityAddress | ReviseEntityAddress) -> dict[str, Any]:
    """The caller-supplied half of an address write, in canonical form.

    Shared by the addition and the correction because the two state the same
    address, which is the same reason `EntityRecordFamilyService._address`
    builds one row for both. The correction's own two fields -- the predecessor
    it names and the version it asserts -- are added by its caller, so a
    correction and an addition carrying identical addresses still hash
    differently, which is correct: they are different acts on different state.
    """
    return {
        "entity_id": command.entity_id,
        "address_type_code": command.address_type_code.value,
        "raw_value": command.raw_value,
        "line1": command.line1,
        "line2": command.line2,
        "city": command.city,
        "region": command.region,
        "postal_code": command.postal_code,
        "country": command.country,
        "label": command.label,
        "is_preferred": command.is_preferred,
        "effective_from": _moment(command.effective_from),
        "effective_to": _moment(command.effective_to),
    }


def _communication_payload(
    command: AddEntityCommunicationMethod | ReviseEntityCommunicationMethod,
) -> dict[str, Any]:
    """The caller-supplied half of a contact-channel write, in canonical form.

    Shared by the addition and the correction on `_address_payload`'s argument:
    the two state the same channel, which is why
    `EntityRecordFamilyService._channel` builds one row for both. The
    correction's own two fields -- the predecessor it names and the version it
    asserts -- are added by its caller, so a correction and an addition carrying
    identical channels still hash differently.

    The normalized value is deliberately absent. `EntityRecordFamilyService`
    derives it from the stated type and value, so it is not a field a caller
    supplied and including it would make the digest depend on a rule the family
    writer owns rather than on what the caller sent.
    """
    return {
        "entity_id": command.entity_id,
        "method_type_code": command.method_type_code.value,
        "usage_context_code": command.usage_context_code.value,
        "display_value": command.display_value,
        "verification_status_code": command.verification_status_code.value,
        "linked_external_identifier_id": command.linked_external_identifier_id,
        "is_preferred": command.is_preferred,
        "effective_from": _moment(command.effective_from),
        "effective_to": _moment(command.effective_to),
    }


def _predecessor(record_id: str, expected_version: int) -> dict[str, Any]:
    """What a supersession's `before_state` truthfully says.

    The predecessor's identity and the version the caller asserted, and nothing
    else. Truthful because the write only succeeded against exactly that row at
    exactly that version -- the guarded `UPDATE` matched no row otherwise -- so
    this is a fact the transaction established rather than a value read back.

    An object rather than a Python `None` for the whole field, which matters at
    the column: `a_mutation_before_state_is_an_object` reads
    `IS NULL OR jsonb_typeof(before_state) = 'object'`, and a Python `None` bound
    to `JSONB` is stored as the JSON value `null`, whose `jsonb_typeof` is
    `'null'`. `SqlEntityRepository.record_mutation_event` binds SQL `null()` for
    an absent state for exactly that reason; a create passes `None` here and a
    supersession passes this.
    """
    return {"record_id": record_id, "version": expected_version}
