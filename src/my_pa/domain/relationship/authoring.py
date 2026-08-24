"""What a governed change to the entity plane is, and how each refusal is named.

The entity plane could be read and not written. `WP-RI-A-02` adds the writes,
and this module holds the two things a write needs before any layer above it can
route one: **which change is being made**, and **which refusal a failure is**.

**The refusals are typed, and that is the whole reason this module exists.**
Until now the repository answered a cross-entity binding conflict and a
retry-exhausted concurrent retirement with the same `ValueError`, differing only
in message. They are opposite facts: the first is permanent and the caller must
stop, the second is transient and the caller should retry. A handler that mapped
`ValueError` to one public code reported a retryable race as a permanent
conflict, and a caller reading that would abandon a write that would have
succeeded on the next attempt. So each refusal is a class, and the class -- not a
string comparison -- is what a handler branches on.

**Two of them still subclass `ValueError`.** `ConflictedIdentifierError` and
`UnsettledBindingError` are raised from `EntitiesRepository.bind_identifier`,
whose published contract says a store that cannot settle the question raises
`ValueError` rather than letting a driver exception out. Narrowing that
contract would break every caller that already handles it, and widening the
exception hierarchy costs nothing: an existing `except ValueError` still catches
them, and a caller that wants to tell the two apart now can. The other classes
carry no `ValueError` base, because no published contract promises one for them.

**No authority, actor class or classification is decided here.** Those are
`domain.relationship.governance`'s vocabularies, already frozen by `2fe4e13fb449`
and already restated as CHECKs; a second declaration of them beside this one
would be a second place the ledger and its writer could disagree.
"""

from __future__ import annotations

from enum import StrEnum

from my_pa.domain.relationship.entity import EntityStatus, ExternalIdentifierNamespace

__all__ = [
    "CALLER_SETTABLE_STATUSES",
    "MAX_ENTITY_NAME_CHARACTERS",
    "MAX_EVIDENCE_REFERENCES",
    "MAX_IDENTIFIER_VALUE_CHARACTERS",
    "MAX_INITIAL_ALIASES",
    "MAX_INITIAL_IDENTIFIERS",
    "AmbiguousEntityError",
    "CallerNamespace",
    "ConflictedIdentifierError",
    "DuplicateEntityFactError",
    "EntityAuthoringError",
    "EntityEvidenceError",
    "EntityIdempotencyConflictError",
    "EntityWriteOperation",
    "HistoricalEntityError",
    "StaleEntityVersionError",
    "UnsettledBindingError",
]

#: The statuses a caller may move an entity to through `entities.update`.
#:
#: The same three `ARCHIVABLE_STATUSES` holds, and deliberately the same three
#: rather than a second list that could drift from it: an entity that can be
#: archived *from* a status is an entity that stands on its own in that status,
#: which is exactly the property that makes it something a caller may ask for.
#:
#: `archived` is absent because `entities.archive` is the capability that writes
#: it and it records `archived_from_status` while doing so -- an update that set
#: `archived` directly would leave the column that makes un-archiving reversible
#: unset, and the schema refuses that. `merged_redirect` is absent because a
#: merge is a governed proposal with a survivor to name, and letting an update
#: assert one would be the identity join `RI-AC-039` reserves from autonomous
#: action, performed by a field.
CALLER_SETTABLE_STATUSES: frozenset[EntityStatus] = frozenset(
    {EntityStatus.ACTIVE, EntityStatus.INACTIVE, EntityStatus.HISTORICAL}
)

#: How many evidence references one write may carry.
#:
#: Bounded for the reason every collection on this plane is bounded: an
#: unbounded list is an unbounded number of rows written by one request, and the
#: rows here are append-only. Small, because evidence for a single corrected
#: mailbox is one or two spans and a request naming twenty is describing
#: something other than one fact.
MAX_EVIDENCE_REFERENCES = 8

#: How many aliases and identifiers `entities.create` may carry with it.
#:
#: A create is allowed to bring the name forms and addresses a caller already
#: has, because making the caller issue four more writes to record what it knew
#: at creation time is how a half-created entity comes to exist. It is not
#: allowed to be a bulk import: each of these is a separate governed record with
#: its own lifecycle, and a create carrying fifty of them is a caller using the
#: one capability with no expected version as a way around the ones that have it.
MAX_INITIAL_ALIASES = 8
MAX_INITIAL_IDENTIFIERS = 8

#: How long a name a caller sends may be, whether it is a display name or one
#: alias of it.
#:
#: The same figure `MENTION_DISPLAY_NAME_LIMIT` uses and deliberately not that
#: constant: these are two rules about two columns that happen to agree today,
#: and importing one into the other would make widening the mention queue's
#: disclosure silently widen what a caller may store as a person's name. The
#: reasoning is the one that constant records -- long enough for a full name
#: with honorifics and a long organization name, short enough that a paragraph
#: of lifted text does not fit -- applied a second time on purpose.
MAX_ENTITY_NAME_CHARACTERS = 200

#: How long an external identity's display value may be.
#:
#: Longer than a name because the widest namespace here is an address, and
#: RFC 5321 puts a mailbox at 320 octets. Wider than every other namespace
#: needs, and that is the right direction for one shared bound: refusing a
#: legitimate long address would refuse the person it belongs to, while
#: admitting an over-long vendor key costs a row that normalization then has to
#: make sense of.
MAX_IDENTIFIER_VALUE_CHARACTERS = 320


class CallerNamespace(StrEnum):
    """The external namespaces a caller may bind an identity in.

    **Seven of the nine `ExternalIdentifierNamespace` holds, and the two that
    are absent are the point.** `legacy_relationship_person_id` and
    `legacy_relationship_organization_id` are the identities the WP-9 substrate
    issued, and an entity carrying one is asserting that it *is* that Person or
    that Organization. That is an identity join between two planes, which
    section 15.3 makes a governed merge with lineage behind it -- and letting a
    caller state it as a namespace on an ordinary bind would perform the merge
    through a field, with no proposal, no decision and no merge record.

    A separate vocabulary rather than a check inside the command, because the
    published MCP schema is derived from the field's own type: a check would
    advertise nine values and refuse two of them, which teaches a model to try
    something the server will not do. What is published is what is admitted.

    Every member's value is one `ExternalIdentifierNamespace` value, and the
    test beside this module holds that -- so a namespace renamed on one side and
    not the other reddens rather than silently becoming unbindable.
    """

    EMAIL = "email"
    ENTRA_OBJECT_ID = "entra_object_id"
    TEAMS_USER_ID = "teams_user_id"
    OUTLOOK_CONTACT_ID = "outlook_contact_id"
    APPLE_CONTACT_ID = "apple_contact_id"
    SOURCE_PARTICIPANT_ID = "source_participant_id"
    VENDOR_SYSTEM_ID = "vendor_system_id"

    @property
    def namespace(self) -> ExternalIdentifierNamespace:
        """The stored namespace this caller-facing member names."""
        return ExternalIdentifierNamespace(self.value)


class EntityWriteOperation(StrEnum):
    """Which governed change one write request makes.

    One vocabulary for every governed change, because one request shape serves them
    all and the repository dispatches on this rather than on a capability
    string. The capability name still travels beside it -- the mutation ledger's
    idempotency unique is `(principal_id, capability, idempotency_key)`, so the
    ledger has to record which capability a key was spent on -- but the *shape*
    of the write is this, and a repository that branched on a public name would
    be a second place the public naming is decided.

    Ten members and no `merge` and no `delete`. A merge is a proposal with a
    decision behind it (`entity_proposals`, section 21.4), and there is no hard
    deletion anywhere on this plane: `retire` and `supersede` are what replace
    it, and both keep the row that resolves a four-year-old message.
    """

    CREATE = "create"
    UPDATE = "update"
    ARCHIVE = "archive"
    RESTORE = "restore"
    BIND_IDENTIFIER = "bind_identifier"
    RETIRE_IDENTIFIER = "retire_identifier"
    SUPERSEDE_IDENTIFIER = "supersede_identifier"
    ADD_ALIAS = "add_alias"
    RETIRE_ALIAS = "retire_alias"
    SUPERSEDE_ALIAS = "supersede_alias"

    @property
    def writes_an_identifier(self) -> bool:
        """Whether this operation's primary record is an external identifier."""
        return self in _IDENTIFIER_OPERATIONS

    @property
    def writes_an_alias(self) -> bool:
        """Whether this operation's primary record is an alias."""
        return self in _ALIAS_OPERATIONS

    @property
    def names_an_existing_child(self) -> bool:
        """Whether this operation names a child record that already exists."""
        return self in _CHILD_TRANSITIONS


_IDENTIFIER_OPERATIONS = frozenset(
    {
        EntityWriteOperation.BIND_IDENTIFIER,
        EntityWriteOperation.RETIRE_IDENTIFIER,
        EntityWriteOperation.SUPERSEDE_IDENTIFIER,
    }
)

_ALIAS_OPERATIONS = frozenset(
    {
        EntityWriteOperation.ADD_ALIAS,
        EntityWriteOperation.RETIRE_ALIAS,
        EntityWriteOperation.SUPERSEDE_ALIAS,
    }
)

_CHILD_TRANSITIONS = frozenset(
    {
        EntityWriteOperation.RETIRE_IDENTIFIER,
        EntityWriteOperation.SUPERSEDE_IDENTIFIER,
        EntityWriteOperation.RETIRE_ALIAS,
        EntityWriteOperation.SUPERSEDE_ALIAS,
    }
)


class EntityAuthoringError(Exception):
    """A governed entity write was refused. The subclass says which refusal."""


class StaleEntityVersionError(EntityAuthoringError):
    """The expected version is not the one the record holds now.

    Nothing was written. The guard is one `UPDATE ... WHERE version = expected`
    whose row count is read before anything else is written, so there is no
    partial state to undo and no successor row to roll back.
    """


class EntityIdempotencyConflictError(EntityAuthoringError):
    """This key is already bound to a materially different request.

    Not "this key was used": a key replayed with the same payload returns the
    original receipt, which is the whole point of having one. This is the other
    case, and answering it with the original receipt would report a write that
    never happened as durable.
    """


class ConflictedIdentifierError(EntityAuthoringError, ValueError):
    """One address is already the current identity of a different entity.

    **Permanent, and this is the half of `bind_identifier`'s `ValueError` that
    a caller must stop on.** Deciding that two entities are the same person is a
    merge, and a merge is a proposal rather than a side effect of a bind, so
    there is nothing the caller can retry that would make this succeed.

    Subclasses `ValueError` because `EntitiesRepository.bind_identifier`'s
    published contract promises one; see the module docstring.
    """


class UnsettledBindingError(EntityAuthoringError, ValueError):
    """A binding could not be settled against a concurrent retirement.

    **Transient, and this is the other half.** Every attempt was refused by an
    active holder that had been retired and committed by another session before
    the read-back could name it. The address may well be free now; the store
    simply could not decide the question inside its own bounded attempts, which
    is a fact about contention rather than about the request.

    Reported as `unavailable` rather than `conflict` for exactly that reason: a
    caller told `conflict` abandons a write that would succeed on the next
    attempt, and a caller told `unavailable` retries it.
    """


class HistoricalEntityError(EntityAuthoringError):
    """The entity named is no longer the one that stands.

    Raised where an entity has been merged away -- `status` is
    `merged_redirect` and `superseded_by_entity_id` names the survivor. A write
    against it is refused rather than followed: silently applying a change to
    the survivor would put a correction on an identity the caller never named,
    and archiving or restoring a redirect would leave a pointer whose target is
    reachable and whose source is not.

    The receipt-shaped answer names the canonical successor, so a caller can
    retarget without being told to guess.
    """


class AmbiguousEntityError(EntityAuthoringError):
    """A create could not be told apart from entities that already exist.

    **The candidates are returned and none of them is chosen.** Section 15.2's
    rule applied at the one moment it is cheapest to apply: an ambiguous
    reference remains unresolved rather than being forced into the nearest
    person, and a create that quietly returned the first match would perform
    exactly the false join the plane exists to avoid -- while reporting success.
    """


class DuplicateEntityFactError(EntityAuthoringError):
    """The change asks for a state the record is already in, or has left.

    Retiring an identifier that is already retired, superseding one that is
    already superseded, or adding an alias this entity actively carries under
    this type. Distinct from `StaleEntityVersionError`, which says the caller
    read an older version: here the version may be current and the transition
    is simply not available from the state the record holds.
    """


class EntityEvidenceError(EntityAuthoringError):
    """An evidence reference names nothing this Principal can cite.

    A reference that is malformed, that names no span, or that names a span
    behind a capture another Principal owns. All three answer alike, because a
    refusal that told the three apart would let a caller learn that an
    identifier names something by watching which refusal came back.
    """
