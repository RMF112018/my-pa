"""What a proposal is allowed to ask for, field by field.

`domain.relationship.governance` holds the proposal record; this module holds
the thing that record carries, and the two are separate files for one reason:
the kind and the fields that kind may name are a single fact, and splitting them
would let a kind exist with no schema to check it against. So
`EntityProposalKind` is declared here, beside the schema, and re-exported from
`governance` where the rest of the plane already reads it.

**Why the payload is typed at all now.** WP-RI-06 stored it as string pairs and
argued that typing six shapes would duplicate six repository signatures the
service already had. That argument held while a proposal was an internal record
no capability could reach. `entities.proposals.create` (WP-05) makes the payload
a *remote caller's* input, and the field set of a caller-supplied mapping is
exactly the surface an untyped column cannot defend: a payload that may carry
any key may carry `principal_id`, `authority`, or `idempotency_key`, and each of
those is a server-owned value the caller would then have named.

**What the schema is, and what it deliberately is not.** Each kind names the
fields of the one canonical command that would carry out that mutation --
`record_alias` names `entities.aliases.add`'s, `end_relationship` names
`entities.relationships.end`'s. The schema owns *which fields exist*: required,
optional, and nothing else. It does not re-check what those fields mean. A
display name is well-formed because `AddEntityAlias.__post_init__` says so, and
a second bounds check here would be a second, weaker constructor for a type that
already has one -- which is the argument the withdrawn
`EntityGovernanceService._apply` made against reconstructing domain records from
flattened strings, and it is still right. `application.entity_promotion` is
where it now holds: the schema's job is that promotion is a *construction*
rather than a translation, so every name in an accepted payload is a name the
command takes and that module renames none of them.

**Three exclusions, and each is a decision rather than an omission.**

`expected_version` and its siblings are absent from every schema because the
proposal has exactly one place a version may be stated -- `expected_target_version`
on the record -- and two places would let them disagree. Which of the two a
promoter believed would then decide whether a stale write was refused.

Evidence references are absent because `entity_proposal_evidence_links` is where
a proposal's evidence lives, and that table carries the Principal and the
composite foreign key that prove the cited record is the proposer's own. A span
identifier sitting in a JSONB payload has neither, so admitting one would let a
proposal cite evidence the evidence table would have refused.

`entities.create`'s `aliases` and `identifiers` are absent because
`record_alias` and `bind_identifier` are kinds of their own. A create carrying
three aliases would put four separate assertions, each resting on its own
evidence, under one reviewer's single accept.

**A value is a string or a boolean.** Not a general JSON value, and the bound is
derived rather than chosen: every field of every canonical command reachable
from a proposal kind is a string (an identifier, an enum member, a name, a
reason, an ISO-8601 instant) or a flag, and the integer fields are all expected
versions -- the one thing a payload may not carry. `null` is absent because an
absent field is how this schema says nothing was proposed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.relationship.authoring import CALLER_SETTABLE_STATUSES
from my_pa.domain.relationship.proposal_validation import validate_proposal_target

__all__ = [
    "FORBIDDEN_PAYLOAD_FIELDS",
    "PROPOSAL_PAYLOAD_VALUE_LIMIT",
    "EntityProposalKind",
    "EntityProposalPayload",
    "PayloadSchema",
    "ProposalPayloadError",
    "dedupe_digest",
    "discriminated_payload_branches",
    "schema_for",
]

#: How long one payload value may be.
#:
#: Stated here rather than imported from `ENTITY_CHANGE_REASON_LIMIT`, which it
#: equals today, for the reason `MAX_ENTITY_NAME_CHARACTERS` states about
#: `MENTION_DISPLAY_NAME_LIMIT`: these are two rules about two columns that
#: happen to agree, and sharing the constant would make widening a stored
#: explanation silently widen what a remote caller may put in a JSONB column.
#:
#: This bound is not a second validation of any field. Each field's real rule
#: belongs to the command that takes it, and `tests/unit/test_entity_proposal_payload`
#: proves this ceiling clears all of them. What it prevents is the failure every
#: unbounded column on this plane is bounded against: a caller putting the
#: document it could not fit anywhere else into the one column with no shape.
PROPOSAL_PAYLOAD_VALUE_LIMIT: Final = 500


class ProposalPayloadError(ValueError):
    """A payload refused to exist. Names the rule, never the value."""


class EntityProposalKind(StrEnum):
    """The mutations a proposal may ask for.

    Seventeen, and every one of them is a mutation this plane can already
    perform -- fifteen through a published `entities.*` capability, and
    `merge_entities` and `split_identity` through the operator-only identity
    correction WP-06 and WP-07 own. A proposal kind naming a write nothing
    performs would be a request nothing could ever accept.

    The last two are the reason `EntityProposal` carries no acceptance effect
    for them: a merge proposal records reviewed intent, and the merge itself is
    a separate operator act. Naming them here is what makes that intent
    recordable; it is not what performs it.
    """

    CREATE_ENTITY = "create_entity"
    UPDATE_ENTITY = "update_entity"
    BIND_IDENTIFIER = "bind_identifier"
    RETIRE_IDENTIFIER = "retire_identifier"
    SUPERSEDE_IDENTIFIER = "supersede_identifier"
    RECORD_ALIAS = "record_alias"
    RETIRE_ALIAS = "retire_alias"
    SUPERSEDE_ALIAS = "supersede_alias"
    RECORD_ASSIGNMENT = "record_assignment"
    REVISE_ASSIGNMENT = "revise_assignment"
    END_ASSIGNMENT = "end_assignment"
    RECORD_RELATIONSHIP = "record_relationship"
    REVISE_RELATIONSHIP = "revise_relationship"
    END_RELATIONSHIP = "end_relationship"
    RESOLVE_MENTION = "resolve_mention"
    MERGE_ENTITIES = "merge_entities"
    SPLIT_IDENTITY = "split_identity"


#: The field names no payload may carry, whatever its kind.
#:
#: Every one of them is refused twice. A per-kind schema admits only the names
#: it lists, so an unlisted name is already refused; this set is checked first
#: and separately, and the redundancy is the point. The schemas are the part of
#: this module that will be edited as kinds are added, and an editor widening one
#: of them cannot re-admit a server-owned field by accident while this set
#: stands in front of them. It also makes the refusal a named rule a test can
#: attack, rather than a consequence of a list nobody wrote down.
#:
#: The names are the ones these values carry elsewhere in this repository, so
#: that a caller copying a field out of a receipt or an audit row and pasting it
#: into a proposal is refused by the name it copied.
FORBIDDEN_PAYLOAD_FIELDS: Final = frozenset(
    {
        # The Principal. `tests/architecture/test_principal_is_never_caller_supplied`
        # holds this for every command; a payload is the one place it could
        # arrive without passing one.
        "principal_id",
        # The proposal's own identity and disposition. A payload naming these
        # would be a payload arguing with the record carrying it.
        "proposal_id",
        "kind",
        "state",
        "dedupe_sha256",
        # The review result. `review.decide` writes these; a proposal that
        # arrived with them filled in would be a proposal that had reviewed
        # itself.
        "review_case_id",
        "decided_by",
        "decided_at",
        "decision_reason",
        "accepted_record_type",
        "accepted_record_id",
        "accepted_record_version",
        "invalidated_reason",
        # Canonical authority: what produced the assertion and under whose
        # class it is recorded. Section 21.4 reserves identity conclusions from
        # autonomous action, and a caller-set `method` is how a model output
        # would be filed as a deterministic match.
        "authority",
        "actor_class",
        "method",
        "method_version",
        "model_id",
        "model_version",
        # Server timestamps. A caller-set moment is a caller-set ordering, and
        # ordering is what every append-only ledger on this plane reads.
        "proposed_at",
        "recorded_at",
        "observed_at",
        "created_at",
        "updated_at",
        "superseded_at",
        # Redirect fields. A payload setting one would perform the identity
        # join that WP-06 reserves to an operator holding a live preview.
        "superseded_by_entity_id",
        "superseded_by_alias_id",
        "superseded_by_identifier_id",
        "superseded_by_assignment_id",
        "superseded_by_relationship_id",
        # Versions. Stated once, on the record, as `expected_target_version`.
        "version",
        "expected_version",
        "expected_entity_version",
        "expected_identifier_version",
        "expected_alias_version",
        "expected_scope_version",
        "expected_from_version",
        "expected_to_version",
        "expected_resolution_version",
        "expected_target_version",
        "expected_review_version",
        # The idempotency key. `adapters.remote_request` already refuses a
        # remote caller's; a payload is the other way in.
        "idempotency_key",
        # Capability and purpose. The authenticated server context owns both.
        "capability",
        "purpose",
        "scope",
        "contract_version",
        "request_id",
        "requested_at",
    }
)


@dataclass(frozen=True, slots=True)
class PayloadSchema:
    """Which fields one proposal kind's payload must and may name."""

    required: frozenset[str]
    optional: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        overlap = self.required & self.optional
        if overlap:
            raise ProposalPayloadError("a payload field is required or optional, not both")
        admitted = self.required | self.optional
        if admitted & FORBIDDEN_PAYLOAD_FIELDS:
            raise ProposalPayloadError("a payload schema admits no server-owned field")

    @property
    def admitted(self) -> frozenset[str]:
        """Every field name this kind's payload may carry."""
        return self.required | self.optional


#: What each kind's payload may name, taken from the canonical command that
#: would carry the mutation out.
#:
#: A mapping rather than a method on the kind, on the argument
#: `_REQUIREMENT_BY_KIND` makes: a schema a proposer could supply is a schema a
#: proposer could widen, and the field set is the whole of what stops a payload
#: naming a server-owned value.
#:
#: `merge_entities` and `split_identity` are the two entries with no command to
#: read: WP-06 owns the first and WP-07 the second, and neither exists at this
#: revision. `merge_entities` names the two entities `EntityMergeRecord` already
#: names, so reviewed intent and the lineage it eventually produces speak about
#: the same pair. `split_identity` names only its subject, deliberately: a Phase
#: B proposal that pre-declared the shape of a split operation would be this
#: phase deciding WP-07's contract from outside it.
_SCHEMA_BY_KIND: Mapping[EntityProposalKind, PayloadSchema] = MappingProxyType(
    {
        EntityProposalKind.CREATE_ENTITY: PayloadSchema(
            required=frozenset({"entity_type", "display_name"}),
            optional=frozenset({"reason"}),
        ),
        EntityProposalKind.UPDATE_ENTITY: PayloadSchema(
            required=frozenset({"entity_id", "reason"}),
            optional=frozenset({"display_name", "canonical_name", "status"}),
        ),
        EntityProposalKind.BIND_IDENTIFIER: PayloadSchema(
            required=frozenset({"entity_id", "namespace", "display_value"}),
            optional=frozenset({"effective_from", "effective_to", "reason"}),
        ),
        EntityProposalKind.RETIRE_IDENTIFIER: PayloadSchema(
            required=frozenset({"entity_id", "identifier_id", "reason"}),
        ),
        EntityProposalKind.SUPERSEDE_IDENTIFIER: PayloadSchema(
            required=frozenset(
                {"entity_id", "identifier_id", "namespace", "display_value", "reason"}
            ),
            optional=frozenset({"effective_from", "effective_to"}),
        ),
        EntityProposalKind.RECORD_ALIAS: PayloadSchema(
            required=frozenset({"entity_id", "alias_type", "display_value"}),
            optional=frozenset({"effective_from", "effective_to", "reason"}),
        ),
        EntityProposalKind.RETIRE_ALIAS: PayloadSchema(
            required=frozenset({"entity_id", "alias_id", "reason"}),
        ),
        EntityProposalKind.SUPERSEDE_ALIAS: PayloadSchema(
            required=frozenset({"entity_id", "alias_id", "alias_type", "display_value", "reason"}),
            optional=frozenset({"effective_from", "effective_to"}),
        ),
        EntityProposalKind.RECORD_ASSIGNMENT: PayloadSchema(
            required=frozenset({"entity_id", "assignment_type"}),
            optional=frozenset(
                {
                    "scope_entity_id",
                    "role",
                    "discipline",
                    "responsibility_class",
                    "effective_from",
                    "effective_to",
                }
            ),
        ),
        # `clear` is absent from both revise schemas although the commands take
        # it: it is a list, and a payload value is a string or a flag. The
        # narrowing is stated rather than silent -- a proposal asks for a value,
        # and blanking a field an earlier accepted proposal put there is a
        # correction a reviewer makes through `correct_and_accept`.
        EntityProposalKind.REVISE_ASSIGNMENT: PayloadSchema(
            required=frozenset({"assignment_id"}),
            optional=frozenset(
                {
                    "role",
                    "discipline",
                    "responsibility_class",
                    "effective_from",
                    "effective_to",
                }
            ),
        ),
        EntityProposalKind.END_ASSIGNMENT: PayloadSchema(
            required=frozenset({"assignment_id", "reason"}),
            optional=frozenset({"effective_end", "end_now"}),
        ),
        EntityProposalKind.RECORD_RELATIONSHIP: PayloadSchema(
            required=frozenset({"from_entity_id", "relationship_type", "to_entity_id"}),
            optional=frozenset({"scope_entity_id", "effective_from", "effective_to"}),
        ),
        EntityProposalKind.REVISE_RELATIONSHIP: PayloadSchema(
            required=frozenset({"relationship_id"}),
            optional=frozenset({"effective_from", "effective_to"}),
        ),
        EntityProposalKind.END_RELATIONSHIP: PayloadSchema(
            required=frozenset({"relationship_id", "reason"}),
            optional=frozenset({"effective_end", "end_now"}),
        ),
        EntityProposalKind.RESOLVE_MENTION: PayloadSchema(
            required=frozenset({"observation_id", "disposition"}),
            optional=frozenset(
                {
                    "entity_id",
                    "entity_type",
                    "canonical_name",
                    "display_name",
                    "rejected_entity_id",
                    "reason",
                }
            ),
        ),
        EntityProposalKind.MERGE_ENTITIES: PayloadSchema(
            required=frozenset({"retained_entity_id", "merged_entity_id"}),
            optional=frozenset({"reason"}),
        ),
        EntityProposalKind.SPLIT_IDENTITY: PayloadSchema(
            required=frozenset({"entity_id"}),
            optional=frozenset({"reason"}),
        ),
    }
)


def schema_for(kind: EntityProposalKind) -> PayloadSchema:
    """Which fields `kind`'s payload must and may name.

    Derived from the kind rather than carried on the proposal, so a payload
    cannot be written against a wider schema than its kind allows -- the shape
    this rule would fail in if it were a column.
    """
    return _SCHEMA_BY_KIND[kind]


def discriminated_payload_branches() -> tuple[dict[str, object], ...]:
    """JSON-Schema branches correlating each proposal kind with its payload.

    The MCP command schema is assembled in the application/adapter boundary,
    but the discriminated payload shape must be generated from the same table
    that validates and digests a proposal. Returning branches rather than a
    complete command schema keeps envelope fields and transport applicators out
    of the domain while giving discovery a closed, self-describing contract.

    Values are strings except for ``end_now``, the sole flag admitted by
    :class:`EntityProposalPayload`. Semantic rules deliberately remain in
    ``validate_proposal_target``; this describes shape and does not create a
    second semantic validator.
    """
    branches: list[dict[str, object]] = []
    for kind in EntityProposalKind:
        schema = schema_for(kind)
        properties = {
            name: {"type": "boolean" if name == "end_now" else "string"}
            for name in sorted(schema.admitted)
        }
        branches.append(
            {
                "properties": {
                    "kind": {"const": kind.value},
                    "payload": {
                        "type": "object",
                        "properties": properties,
                        "required": sorted(schema.required),
                        "additionalProperties": False,
                    },
                },
                "required": ["kind", "payload"],
            }
        )
    return tuple(branches)


#: The one `status` value `update_entity` may not propose, and the reason it
#: needs naming at all: `merged_redirect` is a member of `EntityStatus`, so a
#: schema that admits `status` admits the string. `CALLER_SETTABLE_STATUSES`
#: already records which three a caller may ask for and why the other two are
#: written only by the capability that also writes the column making them
#: reversible or followable. Read from that set rather than restated, because a
#: second list is a list that can drift from the first.
_PROPOSABLE_STATUSES: Final = frozenset(status.value for status in CALLER_SETTABLE_STATUSES)


@dataclass(frozen=True, slots=True)
class EntityProposalPayload:
    """One proposal's requested mutation, checked against its kind's schema.

    `values` is a sorted tuple rather than a mapping for two reasons that both
    matter. It makes the record hashable and comparable, which is what lets
    `record_proposal` refuse rebinding one identifier to different values. And
    it makes `dedupe_digest` depend on content rather than on the iteration
    order of whatever mapping a producer happened to build -- without which two
    runs over the same evidence would produce two digests and dedupe would
    silently stop working.
    """

    kind: EntityProposalKind
    values: tuple[tuple[str, str | bool], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EntityProposalKind):
            raise ProposalPayloadError("a payload names a known proposal kind")
        names = [name for name, _ in self.values]
        if len(set(names)) != len(names):
            raise ProposalPayloadError("a payload names each field once")
        if names != sorted(names):
            raise ProposalPayloadError("a payload's fields are in name order")
        supplied = frozenset(names)
        if supplied & FORBIDDEN_PAYLOAD_FIELDS:
            raise ProposalPayloadError("a payload carries no server-owned field")
        schema = schema_for(self.kind)
        if not supplied <= schema.admitted:
            raise ProposalPayloadError("a payload names only fields its kind's command takes")
        if not schema.required <= supplied:
            raise ProposalPayloadError("a payload names every field its kind requires")
        for name, value in self.values:
            if isinstance(value, bool):
                if name != "end_now":
                    raise ProposalPayloadError("only end_now is a payload flag")
                continue
            if not isinstance(value, str):
                raise ProposalPayloadError("a payload value is a string or a flag")
            if not value.strip():
                raise ProposalPayloadError("a payload names no blank value")
            if len(value) > PROPOSAL_PAYLOAD_VALUE_LIMIT:
                raise ProposalPayloadError("a payload value is bounded")
            if name == "status" and value not in _PROPOSABLE_STATUSES:
                raise ProposalPayloadError("a payload proposes a status a caller may ask for")
        try:
            validate_proposal_target(self.kind.value, dict(self.values))
        except ValueError as exc:
            raise ProposalPayloadError(str(exc)) from exc

    @classmethod
    def of(
        cls, kind: EntityProposalKind, values: Mapping[str, str | bool]
    ) -> EntityProposalPayload:
        """`values` as this kind's payload, in the name order the digest needs."""
        return cls(kind=kind, values=tuple(sorted(values.items())))

    def as_mapping(self) -> dict[str, str | bool]:
        """The requested mutation as the keyword arguments its command takes."""
        return dict(self.values)


def dedupe_digest(payload: EntityProposalPayload) -> str:
    """The digest two identical open proposals collide on.

    Over the kind and the payload, and over nothing else. Not the method: a rule
    and a local model that reach the same conclusion have proposed the same
    change once, and a digest that separated them would put both in front of a
    reviewer. Not the evidence: two sources naming the same alias is
    corroboration, which belongs in `entity_proposal_evidence_links` as a second
    link on one proposal rather than as a second proposal. Not the expected
    target version: including it would let a producer multiply a refused
    proposal by re-reading the target first.

    The encoding is the compact, key-sorted JSON `EntityGovernanceService`
    already digests observations with, so the two digests on this plane are
    produced the same way and neither depends on `dict` ordering.
    """
    encoded = json.dumps(
        {"kind": payload.kind.value, "payload": dict(payload.values)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
