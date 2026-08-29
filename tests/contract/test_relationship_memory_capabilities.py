"""The nine `relationship_memory.` capabilities, as a caller actually meets them.

Beside `tests/contract/test_entity_capabilities.py`, which makes the same kind of
claim about the plane that owns a memory's subject. The repository and the domain
are proved elsewhere; this is about the surface: which names a composed process
publishes, what the published schema says a caller may send, and what the two
transports build from the same document.

Three things are asserted here that no lower layer can assert for itself:

* **A caller cannot self-assert a server-owned field, and the mechanism is
  absence.** The commands have no `authority`, `classification`,
  `cloud_eligible`, `principal_id`, `recorded_at`, `actor` or `review_state`
  field, so the published schema cannot advertise one and a payload naming one is
  refused by the constructor before any handler runs. Both halves are checked,
  because a schema that merely omitted a field a lenient constructor accepted
  would document a rule it does not have.
* **The off switch reaches every surface.** `capabilities.get`, the MCP tool list
  and the remote profile all read `available_capabilities`, so a plane that is off
  is absent from all three — and a write is absent from the remote profile again
  whenever remote writes are disabled.
* **The tool surface supports the sentences a user actually says.** The seventh
  section is seven synthetic conversational turns driven end to end through
  `ApplicationService.invoke` against a real database, and the last section adds
  two more reads on the same runtime: a listing asked for one context, and a
  `get` whose subject was merged away after the note was written. They are marked
  `database`; everything above them is FAST and opens nothing.

Everything is synthetic: invented Principals, invented people, invented notes.
No real person and no live data.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import MISSING, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.engine import make_url
from tests.conftest import (
    FakeProviders,
    FakeUnitOfWork,
    World,
    build_service,
    metadata_for,
    operator,
)

import my_pa.adapters.http.app as http_module
import my_pa.adapters.mcp.server as mcp_module
import my_pa.adapters.normalization as normalization_module
from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import PAYLOAD_KEY, normalize
from my_pa.application.commands import (
    ArchiveRelationshipMemory,
    Command,
    CreateRelationshipMemory,
    GetRelationshipMemory,
    GetRelationshipMemoryHistory,
    ListRelationshipMemories,
    ResolveEntity,
    RestoreRelationshipMemory,
    ReviseRelationshipMemory,
    SearchRelationshipMemories,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.producer_origin import ProducerOrigin, ProducerOriginRegistry
from my_pa.application.service import _HANDLERS, ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import ReviewDecisionRequest, UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.relationship.entity import (
    Entity,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.memory import (
    EvidenceLinkRole,
    MemoryAuthority,
    MemoryKind,
    MemoryLifecycle,
    MemoryProposalMethod,
    MemoryProposalState,
    classification_floor_for,
    memory_proposal_dedupe_digest,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.relationship.resolution import ResolutionOutcome
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory_review import (
    decide_relationship_memory_review,
)
from my_pa.infrastructure.persistence.tables import (
    relationship_memory_proposal_evidence,
    relationship_memory_proposals,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT: Final = Path(__file__).resolve().parents[2]

#: A name distinct from every other database-tier fixture's disposable database.
DISPOSABLE_DATABASE: Final = "my_pa_relationship_memory_capabilities_test"

PRINCIPAL: Final = "prn_cccc0003cccc0003cccc0003"

#: Two synthetic people with distinct names, and two who share one so an
#: ambiguous reference has something real to be ambiguous between.
SARAH: Final = "ent_5aaa0001aaaa0001"
JOHN: Final = "ent_5bbb0002bbbb0002"
SHARED_ONE: Final = "ent_5ccc0003cccc0003"
SHARED_TWO: Final = "ent_5ddd0004dddd0004"

SARAH_NAME: Final = "Sarah Synthetic"
JOHN_NAME: Final = "John Synthetic"
SHARED_NAME: Final = "Robin Synthetic"

#: Verified addresses on invented domains, because a *name* never resolves:
#: "names alone are insufficient", so a lone name match answers `AMBIGUOUS` and
#: the assistant has to hold an identifier before it may write anything.
SARAH_EMAIL: Final = "sarah@synthetic.invalid"
JOHN_EMAIL: Final = "john@synthetic.invalid"

WHEN: Final = datetime(2026, 8, 22, 12, tzinfo=UTC)

#: The floor a `communication_preference` proposal has to meet, read from the
#: domain rule rather than spelled, so a change to the floor moves the fixture
#: with it instead of leaving the server to refuse the insert.
_PROMOTED_CLASSIFICATION: Final = classification_floor_for(MemoryKind.COMMUNICATION_PREFERENCE)

LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)

#: Every capability on the plane, spelled out rather than derived from the
#: prefix. `test_the_nine_names_are_every_name_on_the_plane` is what keeps this
#: from drifting when the plane grows.
MEMORY_CAPABILITIES: Final[tuple[Capability, ...]] = (
    Capability.RELATIONSHIP_MEMORY_CREATE,
    Capability.RELATIONSHIP_MEMORY_GET,
    Capability.RELATIONSHIP_MEMORY_LIST,
    Capability.RELATIONSHIP_MEMORY_SEARCH,
    Capability.RELATIONSHIP_MEMORY_HISTORY,
    Capability.RELATIONSHIP_MEMORY_REVISE,
    Capability.RELATIONSHIP_MEMORY_ARCHIVE,
    Capability.RELATIONSHIP_MEMORY_RESTORE,
    # The ninth (`WP-RI-B-05`), and the guard below is exactly what made adding
    # it a decision here rather than a silent widening of the prefix.
    Capability.RELATIONSHIP_MEMORY_PROPOSE,
)

MEMORY_WRITES: Final[tuple[Capability, ...]] = (
    Capability.RELATIONSHIP_MEMORY_CREATE,
    Capability.RELATIONSHIP_MEMORY_REVISE,
    Capability.RELATIONSHIP_MEMORY_ARCHIVE,
    Capability.RELATIONSHIP_MEMORY_RESTORE,
)

MEMORY_READS: Final[tuple[Capability, ...]] = (
    Capability.RELATIONSHIP_MEMORY_GET,
    Capability.RELATIONSHIP_MEMORY_LIST,
    Capability.RELATIONSHIP_MEMORY_SEARCH,
    Capability.RELATIONSHIP_MEMORY_HISTORY,
)

#: The ninth, which is a write and is in neither tuple above. `WP-RI-B-05`.
#:
#: **A third tuple rather than a fifth row in `MEMORY_WRITES`, and the reason is
#: the claim that tuple carries.** Every sweep over `MEMORY_WRITES` asserts the
#: capability permits `relationship_memory_authoring` and nothing else, which is
#: exactly what this one must not permit: a producer raising a candidate must not
#: hold the grant that writes an accepted memory. Folding it in would either
#: falsify those four assertions or force the purpose map to widen, and widening
#: it is the escalation operator section 12 forbids. The pair below is what this
#: one is asserted against instead.
MEMORY_PROPOSALS: Final[tuple[Capability, ...]] = (Capability.RELATIONSHIP_MEMORY_PROPOSE,)

#: The command each capability builds.
MEMORY_COMMANDS: Final[Mapping[Capability, type]] = {
    Capability.RELATIONSHIP_MEMORY_CREATE: CreateRelationshipMemory,
    Capability.RELATIONSHIP_MEMORY_GET: GetRelationshipMemory,
    Capability.RELATIONSHIP_MEMORY_LIST: ListRelationshipMemories,
    Capability.RELATIONSHIP_MEMORY_SEARCH: SearchRelationshipMemories,
    Capability.RELATIONSHIP_MEMORY_HISTORY: GetRelationshipMemoryHistory,
    Capability.RELATIONSHIP_MEMORY_REVISE: ReviseRelationshipMemory,
    Capability.RELATIONSHIP_MEMORY_ARCHIVE: ArchiveRelationshipMemory,
    Capability.RELATIONSHIP_MEMORY_RESTORE: RestoreRelationshipMemory,
}

#: What the server owns and a caller may not name. Absent from the dataclasses,
#: therefore absent from the published schema, therefore refused on arrival.
SERVER_OWNED_FIELDS: Final[tuple[str, ...]] = (
    "authority",
    "classification",
    "cloud_eligible",
    "principal_id",
    "recorded_at",
    "actor",
    "review_state",
)


def _uncomposed_unit_of_work() -> UnitOfWork:
    """Never called. Listing what a process can serve opens no transaction."""
    raise AssertionError("a capability listing opened a unit of work")


def _service(*, entities: bool, memory: bool) -> ApplicationService:
    """A composed service with the two switches set, and nothing else wired."""
    producer_id = "prn_remote_memory_profile"
    return ApplicationService(
        unit_of_work=_uncomposed_unit_of_work,
        limits=LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=entities,
        relationship_memory_enabled=memory,
        producer_origins=ProducerOriginRegistry(
            {
                producer_id: ProducerOrigin(
                    principal_id=producer_id,
                    principal_kind=PrincipalKind.OPERATOR,
                    method="rule",
                    method_version="synthetic-remote-profile.1",
                )
            }
        ),
    )


# --- the plane is implemented, and named the same way everywhere -------------


def test_the_nine_names_are_every_name_on_the_plane() -> None:
    """Guards every list below: a tenth name would otherwise go untested.

    The tuple is written out rather than derived from the prefix — that is the
    rule `_RELATIONSHIP_MEMORY_CAPABILITIES` follows so admitting a name is a
    decision — and this is the check that pays for it. It paid at `WP-RI-B-05`:
    `relationship_memory.propose` joined the plane and this test is what said the
    lists below had to grow with it.
    """
    by_prefix = {
        capability
        for capability in Capability
        if capability.value.startswith("relationship_memory.")
    }
    assert set(MEMORY_CAPABILITIES) == by_prefix
    assert len(MEMORY_CAPABILITIES) == 9
    assert (set(MEMORY_WRITES) | set(MEMORY_READS) | set(MEMORY_PROPOSALS)) == set(
        MEMORY_CAPABILITIES
    )
    # Three disjoint groups and not two overlapping ones: the producer is not a
    # direct write and is not a read, which is the whole of why it needs a
    # purpose neither of them holds.
    assert not set(MEMORY_WRITES) & set(MEMORY_READS)
    assert not set(MEMORY_PROPOSALS) & (set(MEMORY_WRITES) | set(MEMORY_READS))


@pytest.mark.parametrize("capability", MEMORY_PROPOSALS, ids=lambda c: c.value)
def test_the_producer_holds_a_purpose_neither_half_of_the_plane_holds(
    capability: Capability,
) -> None:
    """`relationship_memory.propose` is the plane's third grant, not a fourth write.

    Operator section 12 keeps a produced candidate out of `relationship_memory.create`
    and section 16 keeps a producer from deciding its own proposal. This is where
    the first of those becomes a property of the *grant*: a client that may raise
    candidates holds `relationship_memory_proposal` and nothing else, so it
    reaches neither the four direct writes nor the four reads.
    """
    assert permitted_purposes(capability) == frozenset({Purpose.RELATIONSHIP_MEMORY_PROPOSAL})
    assert Purpose.RELATIONSHIP_MEMORY_AUTHORING not in permitted_purposes(capability)
    assert Purpose.RELATIONSHIP_MEMORY_READ not in permitted_purposes(capability)
    for other in (*MEMORY_WRITES, *MEMORY_READS):
        assert Purpose.RELATIONSHIP_MEMORY_PROPOSAL not in permitted_purposes(other)


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_has_a_handler(capability: Capability) -> None:
    """A published name with no handler is a `KeyError` at dispatch time."""
    assert capability in _HANDLERS


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_a_build_with_the_plane_off_withholds_every_name(capability: Capability) -> None:
    """Off is the default, and off has to mean absent rather than refused later.

    `capabilities.get`, the MCP tool list and the remote profile all read this
    one answer, so a name published here would be published by all three in a
    process that cannot serve it.
    """
    assert capability not in _service(entities=True, memory=False).available_capabilities


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_the_plane_also_needs_the_entity_plane_it_binds_subjects_from(
    capability: Capability,
) -> None:
    """Two switches, not one.

    A memory's subject is an Entity and the repository proves ownership of it by
    reading the entity table, so a build serving memories without the plane that
    owns their subjects would be serving writes it cannot validate.
    """
    assert capability not in _service(entities=False, memory=True).available_capabilities


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_a_build_with_the_plane_on_publishes_every_name(capability: Capability) -> None:
    assert capability in _service(entities=True, memory=True).available_capabilities


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_the_mcp_tool_list_carries_every_name_with_a_description(
    capability: Capability,
) -> None:
    """A tool a model can see but not read about is a tool it will misuse.

    The description is the command's own first documented line and is the whole
    of the model-facing documentation for the capability, so an empty one is a
    published tool with no stated meaning.
    """
    tools = {tool.name: tool for tool in published_tools(_service(entities=True, memory=True))}
    assert capability.value in tools
    description = tools[capability.value].description
    assert description is not None
    assert description.strip() != ""


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_the_mcp_tool_list_withholds_every_name_when_the_plane_is_off(
    capability: Capability,
) -> None:
    published = {tool.name for tool in published_tools(_service(entities=True, memory=False))}
    assert capability.value not in published


# --- the published payload schema --------------------------------------------


@pytest.mark.parametrize(
    "command_type",
    [CreateRelationshipMemory, ReviseRelationshipMemory],
    ids=["create", "revise"],
)
def test_a_write_schema_closes_the_object(command_type: type) -> None:
    """An open object would advertise that unknown fields are acceptable.

    The constructor refuses them either way; the schema is what a model reads
    before it sends one.
    """
    assert payload_schema_for(command_type)["additionalProperties"] is False


@pytest.mark.parametrize(
    "command_type",
    [CreateRelationshipMemory, ReviseRelationshipMemory],
    ids=["create", "revise"],
)
@pytest.mark.parametrize("forbidden", SERVER_OWNED_FIELDS)
def test_a_write_schema_publishes_no_server_owned_field(command_type: type, forbidden: str) -> None:
    """The mechanism is absence: the field does not exist on the dataclass.

    If any of these were published, a caller could self-assert the authority of
    a note, lower its classification, mark it cloud eligible, or claim to be a
    different Principal.
    """
    assert forbidden not in payload_schema_for(command_type)["properties"]


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        (
            Capability.RELATIONSHIP_MEMORY_CREATE,
            {
                "entity_id": SARAH,
                "statement": "Synthetic subject prefers Teams messages.",
                "idempotency_key": "synthetic-schema-0001",
            },
        ),
        (
            Capability.RELATIONSHIP_MEMORY_REVISE,
            {
                "memory_id": "mem_aaaa0001aaaa0001",
                "expected_version": 1,
                "statement": "Synthetic subject prefers phone calls.",
                "idempotency_key": "synthetic-schema-0002",
            },
        ),
    ],
    ids=["create", "revise"],
)
@pytest.mark.parametrize("forbidden", SERVER_OWNED_FIELDS)
def test_a_payload_naming_a_server_owned_field_is_refused(
    capability: Capability, payload: dict[str, Any], forbidden: str
) -> None:
    """And the same payload without it is accepted, so the refusal is about the field.

    Both halves in one test on purpose: a constructor that refused everything
    would pass the negative assertion alone.
    """
    accepted = normalize(capability.value, _envelope(capability, payload))
    assert isinstance(accepted[1], MEMORY_COMMANDS[capability])
    with pytest.raises(InvalidRequestError):
        normalize(capability.value, _envelope(capability, {**payload, forbidden: "anything"}))


def test_the_kind_property_publishes_the_closed_vocabulary_as_an_enum() -> None:
    """A model that cannot see the ten members guesses at them.

    The command holds a `MemoryKind` rather than a string precisely so the
    schema can publish the vocabulary; a string field would document nothing.
    """
    published = payload_schema_for(CreateRelationshipMemory)["properties"]["kind"]
    assert published["type"] == "string"
    assert published["enum"] == [member.value for member in MemoryKind]
    assert len(published["enum"]) == 10


def test_the_lifecycle_property_publishes_the_closed_vocabulary_as_an_enum() -> None:
    """Two members, and no third that could read as "deleted"."""
    published = payload_schema_for(ListRelationshipMemories)["properties"]["lifecycle"]
    assert published["type"] == "string"
    assert published["enum"] == [member.value for member in MemoryLifecycle]
    assert published["enum"] == ["active", "archived"]


# --- normalization ------------------------------------------------------------


def _envelope(capability: Capability, payload: Mapping[str, Any]) -> dict[str, Any]:
    """One wire document: the envelope's fields, and the payload beside them.

    This is exactly the shape `normalize` reads, which is what both transports
    hand it — HTTP the decoded body, MCP the tool call's arguments.
    """
    return {
        "request_id": f"req-{capability.value}",
        "purpose": _a_permitted_purpose(capability).value,
        "principal_id": PRINCIPAL,
        "requested_at": "2026-08-22T12:00:00Z",
        PAYLOAD_KEY: dict(payload),
    }


def _a_permitted_purpose(capability: Capability) -> Purpose:
    return sorted(permitted_purposes(capability))[0]


def test_a_caller_string_becomes_the_closed_vocabulary_member() -> None:
    """JSON has no enum, and the command refuses anything that is not one.

    Without the conversion a caller's `"important_date"` would be refused for
    being a string rather than for naming an unknown kind.
    """
    _, built = normalize(
        Capability.RELATIONSHIP_MEMORY_CREATE.value,
        _envelope(
            Capability.RELATIONSHIP_MEMORY_CREATE,
            {
                "entity_id": JOHN,
                "kind": "important_date",
                "statement": "John Synthetic's birthday is April 17.",
                "idempotency_key": "synthetic-kind-0001",
            },
        ),
    )
    assert isinstance(built, CreateRelationshipMemory)
    assert built.kind is MemoryKind.IMPORTANT_DATE


def test_an_unknown_kind_is_refused_rather_than_coerced() -> None:
    """A kind outside the vocabulary is left as it arrived so the command reports
    it under its own field name rather than under a second copy of the mapping."""
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.RELATIONSHIP_MEMORY_CREATE.value,
            _envelope(
                Capability.RELATIONSHIP_MEMORY_CREATE,
                {
                    "entity_id": JOHN,
                    "kind": "medical_condition",
                    "statement": "A synthetic note.",
                    "idempotency_key": "synthetic-kind-0002",
                },
            ),
        )


def test_both_transports_reach_the_application_through_one_normalization() -> None:
    """The structural half of the parity claim.

    A comparison of two outputs proves the two agreed today. What holds the
    property is that there is nothing to disagree: both transports call the same
    function object.
    """
    assert http_module.normalize is normalization_module.normalize
    assert mcp_module.normalize is normalization_module.normalize


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        (
            Capability.RELATIONSHIP_MEMORY_CREATE,
            {
                "entity_id": SARAH,
                "kind": "communication_preference",
                "statement": "Sarah Synthetic prefers Teams messages.",
                "structured_value": {"channel": "teams", "preference": "preferred"},
                "context_links": [
                    {"target_type": "entity", "target_id": JOHN, "role": "related_to"}
                ],
                "observed_at": "2026-08-22T11:00:00Z",
                "idempotency_key": "synthetic-parity-0001",
            },
        ),
        (
            Capability.RELATIONSHIP_MEMORY_LIST,
            {"entity_id": SARAH, "kinds": ["communication_preference"], "lifecycle": "archived"},
        ),
    ],
    ids=["create", "list"],
)
def test_http_and_mcp_build_the_same_command_from_the_same_payload(
    capability: Capability, payload: dict[str, Any]
) -> None:
    """The comparative half. Each transport's own document, one command.

    HTTP hands `normalize` the decoded JSON body; MCP hands it the tool call's
    arguments through its own bounding step. Both documents are built here the
    way each transport builds them, and the commands are compared as values —
    including the enum members, the tuples and the nested link objects, which are
    exactly where a second normalization would drift.
    """
    document = _envelope(capability, payload)
    over_http = normalize(capability.value, json.loads(json.dumps(document)))
    over_mcp = normalize(capability.value, mcp_module._document(document))
    assert over_http[1] == over_mcp[1]
    assert over_http[0] == over_mcp[0]


#: The three writes that change a memory that already exists, and one payload
#: each that is complete except for `expected_version`. A create is absent on
#: purpose: it depends on no prior state, so there is no version for it to have
#: read, and demanding one would be a rule with nothing behind it.
STATE_DEPENDENT_WRITES: Final[tuple[tuple[Capability, dict[str, Any]], ...]] = (
    (
        Capability.RELATIONSHIP_MEMORY_REVISE,
        {
            "memory_id": "mem_aaaa0001aaaa0001",
            "statement": "Synthetic subject prefers phone calls.",
            "idempotency_key": "synthetic-expected-0001",
        },
    ),
    (
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        {
            "memory_id": "mem_aaaa0001aaaa0001",
            "idempotency_key": "synthetic-expected-0002",
        },
    ),
    (
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        {
            "memory_id": "mem_aaaa0001aaaa0001",
            "idempotency_key": "synthetic-expected-0003",
        },
    ),
)


@pytest.mark.parametrize(
    ("capability", "payload"),
    STATE_DEPENDENT_WRITES,
    ids=[capability.value for capability, _ in STATE_DEPENDENT_WRITES],
)
def test_a_state_dependent_write_is_refused_without_an_expected_version(
    capability: Capability, payload: dict[str, Any]
) -> None:
    """`RM-API-AC-006`: the caller states the version it read, or it does not write.

    Lost-update protection that a caller can decline is not protection: a revise,
    an archive or a restore that omitted the version would silently overwrite
    whatever arrived between the read and the write. The field therefore carries
    no default on any of the three commands, so a payload without it is refused
    at the transport boundary before a handler runs — which is what this asserts,
    together with the same payload *with* it being accepted, so the refusal is
    about the missing field and not about the payload being malformed in some
    other way.

    Both halves matter and the negative half is the lethal one. Give
    `expected_version` any default — `1`, or `None` with a "keep current" reading
    — and `normalize` stops raising, which is the one change that turns this
    plane's optimistic concurrency into a suggestion. Before this test the
    property was true structurally and asserted nowhere.
    """
    with pytest.raises(InvalidRequestError):
        normalize(capability.value, _envelope(capability, payload))

    _, accepted = normalize(
        capability.value, _envelope(capability, {**payload, "expected_version": 1})
    )
    assert isinstance(accepted, MEMORY_COMMANDS[capability])
    assert isinstance(
        accepted,
        ReviseRelationshipMemory | ArchiveRelationshipMemory | RestoreRelationshipMemory,
    )
    assert accepted.expected_version == 1


@pytest.mark.parametrize(
    "command",
    [ReviseRelationshipMemory, ArchiveRelationshipMemory, RestoreRelationshipMemory],
    ids=["revise", "archive", "restore"],
)
def test_no_state_dependent_write_command_gives_expected_version_a_default(
    command: type[ReviseRelationshipMemory]
    | type[ArchiveRelationshipMemory]
    | type[RestoreRelationshipMemory],
) -> None:
    """The structural half, stated where a reader can check it.

    The refusal above is a consequence of this and not a second rule, so it is
    asserted rather than described: a dataclass field with no default is what
    makes the constructor raise, and `MISSING` is how that reads in `dataclasses`.
    Both spellings of a default are checked, because `default_factory` would
    supply one just as effectively and leave `default` untouched.
    """
    declared = {field.name: field for field in fields(command)}
    assert declared["expected_version"].default is MISSING
    assert declared["expected_version"].default_factory is MISSING


# --- purposes and scope --------------------------------------------------------


@pytest.mark.parametrize("capability", MEMORY_WRITES, ids=lambda c: c.value)
def test_a_write_is_reachable_only_under_the_authoring_purpose(
    capability: Capability,
) -> None:
    """A grant issued so an assistant can recall what the user recorded must not
    also let it write new assertions about that person."""
    assert permitted_purposes(capability) == frozenset({Purpose.RELATIONSHIP_MEMORY_AUTHORING})


@pytest.mark.parametrize("capability", MEMORY_READS, ids=lambda c: c.value)
def test_a_read_is_reachable_only_under_the_read_purpose(capability: Capability) -> None:
    assert permitted_purposes(capability) == frozenset({Purpose.RELATIONSHIP_MEMORY_READ})


@pytest.mark.parametrize("capability", MEMORY_WRITES, ids=lambda c: c.value)
def test_the_read_purpose_cannot_invoke_a_write(capability: Capability) -> None:
    """Stated from the other direction, because this is the claim that matters."""
    assert Purpose.RELATIONSHIP_MEMORY_READ not in permitted_purposes(capability)


@pytest.mark.parametrize("capability", MEMORY_READS, ids=lambda c: c.value)
def test_the_authoring_purpose_does_not_reach_a_read_either(capability: Capability) -> None:
    """The plane holds a pair rather than one grant covering both, so neither
    implies the other."""
    assert Purpose.RELATIONSHIP_MEMORY_AUTHORING not in permitted_purposes(capability)


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_is_scopeless(capability: Capability) -> None:
    """A memory names an Entity, not a source.

    Its rows carry no `source_id` and no `enrollment_id`, so requiring a declared
    scope would make the whole plane permanently unusable and naming one would be
    naming a grant this plane cannot hold.
    """
    assert capability in _SCOPELESS


# --- the remote profile ---------------------------------------------------------


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_no_capability_on_the_plane_is_operator_only(capability: Capability) -> None:
    """Guards the two profile assertions below, which skip operator-only names."""
    assert not is_operator_only(capability)


@pytest.mark.parametrize("capability", MEMORY_WRITES, ids=lambda c: c.value)
def test_a_write_is_excluded_from_the_remote_profile_when_remote_writes_are_off(
    capability: Capability,
) -> None:
    """The remote surface classifies by purpose, with no per-capability list.

    `relationship_memory_authoring` is in the write set, so the four writes leave
    the profile the moment remote writes are disabled — and the four reads stay,
    which is what makes this a classification rather than a blanket refusal.
    """
    profile = remote_tool_names(_service(entities=True, memory=True), writes_enabled=False)
    assert capability.value not in profile


@pytest.mark.parametrize("capability", MEMORY_READS, ids=lambda c: c.value)
def test_a_read_stays_in_the_remote_profile_when_remote_writes_are_off(
    capability: Capability,
) -> None:
    profile = remote_tool_names(_service(entities=True, memory=True), writes_enabled=False)
    assert capability.value in profile


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_joins_the_remote_profile_when_writes_are_enabled(
    capability: Capability,
) -> None:
    profile = remote_tool_names(_service(entities=True, memory=True), writes_enabled=True)
    assert capability.value in profile


@pytest.mark.parametrize("capability", MEMORY_CAPABILITIES, ids=lambda c: c.value)
def test_no_capability_reaches_the_remote_profile_when_the_plane_is_off(
    capability: Capability,
) -> None:
    """The profile is derived from the composed set, so the off switch reaches it."""
    profile = remote_tool_names(_service(entities=True, memory=False), writes_enabled=True)
    assert capability.value not in profile


# --- the in-memory double answers what the server answers ------------------------
#
# `tests/conftest._RelationshipMemories` stands in for the SQL repository
# everywhere the FAST tier drives this plane, so a double that disagrees with
# production quietly turns every test above it into evidence about the double.
# This section is FAST and opens nothing; the server's own answer to the same
# question is `tests/database/test_relationship_memory_repository.py`.


def _over_the_double() -> tuple[ApplicationService, Principal, str]:
    """The composed service over the in-memory plane, and one synthetic subject.

    `tests/conftest.build_service` is the FAST-tier composition — the same
    `ApplicationService` this file inspects above, over `FakeUnitOfWork` instead
    of over PostgreSQL — so a turn driven through it reaches the double by the
    route a caller reaches the server, rather than by calling the repository
    directly and asserting about an object no capability returns.
    """
    world = World()
    principal = operator(PRINCIPAL)
    FakeUnitOfWork(world).entities.create(PRINCIPAL, _an_entity(SARAH, SARAH_NAME))
    return build_service(world, FakeProviders(), LIMITS), principal, SARAH


def _answered(
    service: ApplicationService, principal: Principal, request: Command
) -> dict[str, Any]:
    """One turn through the composed service, refused nothing."""
    envelope = service.invoke(
        metadata_for(request.capability, _a_permitted_purpose(request.capability), principal),
        request,
        principal=principal,
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return dict(envelope.result)


def _the_one_memory(
    service: ApplicationService, principal: Principal, subject: str
) -> Mapping[str, Any]:
    """The single memory the listing discloses about `subject`.

    Read through `relationship_memory.list` rather than off the repository,
    because the listing is where `pinned` is published and therefore where a
    caller would have met the wrong value.
    """
    listed = _answered(service, principal, ListRelationshipMemories(entity_id=subject))
    memories = listed["memories"]
    assert isinstance(memories, list)
    assert len(memories) == 1
    entry = memories[0]
    assert isinstance(entry, Mapping)
    return entry


def test_a_revise_through_the_double_treats_an_absent_pin_as_the_server_does() -> None:
    """The double contradicted production, and no test could see it.

    `_RelationshipMemories._mutate` wrote `request.pinned` whenever it was
    revising. A revise that says nothing about the pin sends `None` — the
    command's default, and the field's whole point — so the double put `None`
    onto a `bool` field and `relationship_memory.list` published
    `"pinned": null` where the SQL repository publishes the value it carried
    forward. Nothing caught it because no FAST test had ever revised a *pinned*
    memory through the double.

    Both halves, exactly as the database tests state them for the server: absent
    keeps the pin, explicit `False` unpins. The second is not decoration — it is
    what stops the fix being "never write `pinned` on a revise", which would
    agree with the first half while making unpinning impossible.
    """
    service, principal, subject = _over_the_double()
    created = _answered(
        service,
        principal,
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.COMMUNICATION_PREFERENCE,
            statement="Sarah Synthetic prefers Teams messages.",
            pinned=True,
            idempotency_key="double-pin-0001",
        ),
    )
    assert created["created"] is True
    assert _the_one_memory(service, principal, subject)["pinned"] is True

    revised = _answered(
        service,
        principal,
        ReviseRelationshipMemory(
            memory_id=str(created["memory_id"]),
            expected_version=int(created["version"]),
            statement="Sarah Synthetic prefers Teams messages, and replies fastest before noon.",
            correction_reason="a wording correction that says nothing about the pin",
            idempotency_key="double-pin-0002",
        ),
    )
    assert _the_one_memory(service, principal, subject)["pinned"] is True

    _answered(
        service,
        principal,
        ReviseRelationshipMemory(
            memory_id=str(created["memory_id"]),
            expected_version=int(revised["version"]),
            statement="Sarah Synthetic prefers Teams messages.",
            pinned=False,
            idempotency_key="double-pin-0003",
        ),
    )
    assert _the_one_memory(service, principal, subject)["pinned"] is False


def test_a_listing_publishes_authority_and_classification_beside_every_kind() -> None:
    """`RM-AC-019`: the two provenance fields reach the wire, on both listing reads.

    Through `invoke` rather than off `MemoryPage`, because carrying the values on
    the port and dropping them in `_memory_summary_view` is exactly the shape of
    the defect this covers: the repository already selected `classification`
    while the rendered view emitted neither field.

    `search` is asserted beside `list` because each is a separate capability over
    the one view function, and a caller reaching the plane by a term rather than
    by an entity must be able to make the same judgement about what it found.
    """
    service, principal, subject = _over_the_double()
    _answered(
        service,
        principal,
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.COMMUNICATION_PREFERENCE,
            statement="Sarah Synthetic prefers Teams messages.",
            idempotency_key="double-authority-0001",
        ),
    )
    listed = _the_one_memory(service, principal, subject)
    assert listed["authority"] == MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE.value
    assert listed["classification"] == Classification.PRIVATE_LOCAL.value

    searched = _answered(service, principal, SearchRelationshipMemories(query="Teams"))
    matches = searched["memories"]
    assert isinstance(matches, list)
    assert [entry["authority"] for entry in matches] == [
        MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE.value
    ]
    assert [entry["classification"] for entry in matches] == [Classification.PRIVATE_LOCAL.value]


def test_withholding_the_statement_still_states_where_the_memory_came_from() -> None:
    """The statement is the caller's choice; the provenance is not.

    A caller that asks for a listing without the notes is asking not to be handed
    the text — an index, a count, a picker. It is not asking to be told less about
    where each record came from, and `authority` is the field that decides whether
    a line may be presented as something known or only as something the user once
    wrote. Both directions are asserted, because "always emitted" and "emitted
    only when the statement is" are indistinguishable from one call.
    """
    service, principal, subject = _over_the_double()
    _answered(
        service,
        principal,
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.COMMUNICATION_PREFERENCE,
            statement="Sarah Synthetic prefers Teams messages.",
            idempotency_key="double-authority-0002",
        ),
    )
    withheld = _answered(
        service,
        principal,
        ListRelationshipMemories(entity_id=subject, include_statement=False),
    )["memories"]
    assert isinstance(withheld, list)
    assert len(withheld) == 1
    assert "statement" not in withheld[0]
    assert withheld[0]["authority"] == MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE.value
    assert withheld[0]["classification"] == Classification.PRIVATE_LOCAL.value
    assert "statement" in _the_one_memory(service, principal, subject)


# --- the conversational flows, end to end ---------------------------------------
#
# Seven turns a user actually says, driven through `ApplicationService.invoke`
# against a real database. These are the claim the sections above cannot make:
# that the capabilities compose into the sequence a model would have to perform.


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


def _an_entity(entity_id: str, display_name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


class _Assistant:
    """The composed service, and one method that sends a turn through it.

    Two engines, exactly as the gateway composes them: the audit sink draws its
    connection from the second and commits there, so an audit row survives a
    rolled-back request.
    """

    def __init__(self, url: str) -> None:
        self.work_engine: Engine = create_database_engine(url)
        self.audit_engine: Engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            # The plane's composition is stated on the unit of work as well as on
            # the service, exactly as `bootstrap.gateway` states it: the review
            # surface is inside the transaction and cannot read the service's
            # switches, so a build that publishes this plane's capability names
            # while its unit of work does not reach the plane would be giving two
            # different answers to one question.
            return SqlAlchemyUnitOfWork(
                self.work_engine, audit=audit, relationship_memory_enabled=True
            )

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            clock=lambda: WHEN,
            relationship_intelligence_enabled=True,
            relationship_memory_enabled=True,
        )
        self.principal = Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        )

    def close(self) -> None:
        self.work_engine.dispose()
        self.audit_engine.dispose()

    def send(self, request: Command, *, purpose: Purpose | None = None) -> ResponseEnvelope:
        capability = request.capability
        metadata = RequestMetadata(
            request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
            capability=capability,
            purpose=_a_permitted_purpose(capability) if purpose is None else purpose,
            principal_id=PRINCIPAL,
            requested_at=WHEN,
        )
        return self.service.invoke(metadata, request, principal=self.principal)

    def result(self, request: Command, *, purpose: Purpose | None = None) -> dict[str, Any]:
        envelope = self.send(request, purpose=purpose)
        assert envelope.error is None, envelope.error
        assert envelope.result is not None
        return dict(envelope.result)


def _a_verified_address(entity_id: str, address: str, suffix: str) -> ExternalIdentifier:
    return ExternalIdentifier(
        identifier_id=f"xid_{suffix}",
        entity_id=entity_id,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
        display_value=address,
        principal_id=PRINCIPAL,
        verified=True,
    )


@pytest.fixture
def assistant(disposable_database: str) -> Iterator[_Assistant]:
    """A migrated database holding four synthetic people, and the composed service.

    Two of them share a name, so an ambiguous reference has something real to be
    ambiguous between; two hold a verified address, because that is what an
    assistant must have before it may write anything against an identity.
    """
    alembic_command.upgrade(_config(), "head")
    composed = _Assistant(disposable_database)
    with composed.work_engine.begin() as connection:
        entities = SqlEntityRepository(connection)
        entities.create(PRINCIPAL, _an_entity(SARAH, SARAH_NAME))
        entities.create(PRINCIPAL, _an_entity(JOHN, JOHN_NAME))
        entities.create(PRINCIPAL, _an_entity(SHARED_ONE, SHARED_NAME))
        entities.create(PRINCIPAL, _an_entity(SHARED_TWO, SHARED_NAME))
        entities.bind_identifier(
            PRINCIPAL, SARAH, _a_verified_address(SARAH, SARAH_EMAIL, "5aaa0001aaaa0001")
        )
        entities.bind_identifier(
            PRINCIPAL, JOHN, _a_verified_address(JOHN, JOHN_EMAIL, "5bbb0002bbbb0002")
        )
    try:
        yield composed
    finally:
        composed.close()


def _resolved(assistant: _Assistant, address: str) -> str:
    """The one entity a verified address names.

    An address rather than a name, and that is the plane's rule rather than this
    file's convenience: a lone canonical-name match answers `AMBIGUOUS`, because
    names alone are insufficient and there is no number of name matches at which
    a name becomes an identifier.
    """
    resolution = assistant.result(
        ResolveEntity(reference=address, namespace=ExternalIdentifierNamespace.EMAIL.value)
    )["resolution"]
    assert resolution["outcome"] == ResolutionOutcome.RESOLVED_EXACT.value, resolution
    entity_id = resolution["entity_id"]
    assert isinstance(entity_id, str)
    return entity_id


@pytest.mark.database
def test_remember_that_sarah_prefers_teams_messages(assistant: _Assistant) -> None:
    """Turn 1: resolve the person first, then record the note against what came back.

    The note is written against the identifier resolution produced and never
    against the words the user said, which is the whole ordering the plane
    depends on.
    """
    subject = _resolved(assistant, SARAH_EMAIL)
    assert subject == SARAH
    receipt = assistant.result(
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.COMMUNICATION_PREFERENCE,
            statement="Sarah Synthetic prefers Teams messages.",
            structured_value={"channel": "teams", "preference": "preferred"},
            idempotency_key="turn-one-0001",
        )
    )
    assert receipt["created"] is True
    assert receipt["version"] == 1
    assert receipt["lifecycle"] == MemoryLifecycle.ACTIVE.value
    # The receipt acknowledges a durable record and echoes no note back.
    assert "statement" not in receipt


@pytest.mark.database
def test_what_do_i_know_about_sarah(assistant: _Assistant) -> None:
    """Turn 2: the listing is the "what do I know about this person" capability."""
    subject = _resolved(assistant, SARAH_EMAIL)
    assistant.result(
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.COMMUNICATION_PREFERENCE,
            statement="Sarah Synthetic prefers Teams messages.",
            idempotency_key="turn-two-0001",
        )
    )
    listed = assistant.result(ListRelationshipMemories(entity_id=subject))
    memories = listed["memories"]
    assert isinstance(memories, list)
    assert [entry["statement"] for entry in memories] == ["Sarah Synthetic prefers Teams messages."]
    assert [entry["kind"] for entry in memories] == [MemoryKind.COMMUNICATION_PREFERENCE.value]
    assert [entry["authority"] for entry in memories] == [
        MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE.value
    ]
    assert listed["memories_withheld_by_policy"] == 0


def _an_evidence_id() -> str:
    """One proposal-evidence identifier. Named so the insert below fits a line."""
    return issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE)


def _a_promoted_assertion(engine: Engine, subject: str, statement: str) -> str:
    """One reviewer-accepted proposal on `subject`, and the memory it became.

    Written as direct inserts for the reason
    `tests/database/test_relationship_memory_review.py` gives: no producer of
    proposals exists, and inventing one here would make this a test of the
    invention. The rows are what a producer would have to write, and the schema's
    own CHECKs police that.

    It is here rather than borrowed from that module because the claim is about
    the *assistant's* listing: the memory has to arrive in the same database the
    composed service reads, through the route the plane says is the only one that
    can produce a non-`user_authored_private_note` authority.
    """
    review_case_id = issue_identifier(IdKind.REVIEW_CASE)
    memory_proposal_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
    with engine.begin() as connection:
        connection.execute(
            insert(relationship_memory_proposals).values(
                memory_proposal_id=memory_proposal_id,
                principal_id=PRINCIPAL,
                subject_entity_id=subject,
                origin_subject_entity_id=subject,
                expected_subject_version=1,
                proposed_kind=MemoryKind.COMMUNICATION_PREFERENCE.value,
                proposed_statement=statement,
                proposed_statement_sha256=statement_digest(statement),
                dedupe_sha256=memory_proposal_dedupe_digest(
                    principal_id=PRINCIPAL,
                    subject_entity_id=subject,
                    proposed_kind=MemoryKind.COMMUNICATION_PREFERENCE,
                    proposed_statement_sha256=statement_digest(statement),
                    structured_value=None,
                ),
                structured_value=None,
                state=MemoryProposalState.NEEDS_REVIEW.value,
                method=MemoryProposalMethod.RULE.value,
                method_version="synthetic-rule-v1",
                model_id=None,
                model_version=None,
                classification=_PROMOTED_CLASSIFICATION.value,
                proposed_at=WHEN,
                review_case_id=review_case_id,
                accepted_memory_id=None,
                accepted_memory_version_id=None,
                invalidated_reason=None,
            )
        )
        # One evidence row, because it is what decides the authority: an
        # acceptance resting on nothing is `user_confirmed_assertion` — the
        # reviewer's own word — and only an evidence-backed one becomes
        # `source_backed_assertion`, which is the value this test is about.
        connection.execute(
            insert(relationship_memory_proposal_evidence).values(
                proposal_evidence_id=_an_evidence_id(),
                memory_proposal_id=memory_proposal_id,
                principal_id=PRINCIPAL,
                role=EvidenceLinkRole.DIRECT.value,
                entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
                capture_span_id=None,
                knowledge_id=None,
                created_at=WHEN,
            )
        )
    with engine.begin() as connection:
        decision = decide_relationship_memory_review(
            connection,
            ReviewDecisionRequest(
                review_case_id=review_case_id,
                expected_review_version=0,
                disposition=Disposition.ACCEPT,
                principal_id=PRINCIPAL,
                correlation_id=issue_identifier(IdKind.CORRELATION),
                audit_id=issue_identifier(IdKind.AUDIT),
                policy_version="policy-v1",
                decided_at=WHEN,
                corrected_value=None,
            ),
        )
    assert decision.proposal_state is ProposalState.ACCEPTED
    # Read off the proposal, which is where the promotion stamps it: the decision
    # record is the capture plane's shape and carries no memory identifier.
    with engine.connect() as connection:
        accepted = connection.execute(
            select(relationship_memory_proposals.c.accepted_memory_id).where(
                relationship_memory_proposals.c.memory_proposal_id == memory_proposal_id
            )
        ).scalar_one()
    assert isinstance(accepted, str)
    return accepted


@pytest.mark.database
def test_the_assistants_listing_tells_a_promoted_finding_from_the_users_own_note(
    assistant: _Assistant,
) -> None:
    """`RM-AC-019` at the surface a model reads: two rows, one distinguishing field.

    This is the functional claim behind the field, and it can only be made here.
    An assistant answering "what do I know about Sarah?" gets a list, and it must
    not present a line a reviewer promoted from a source the way it presents a
    line the user typed — one is a finding, the other is a note. Both memories
    are on one subject, of one kind, unpinned and active, so `authority` is the
    only field in the payload that separates them.

    Driven through `ApplicationService.invoke`, because the values exist on the
    port and existed on the version long before they reached the wire: the whole
    defect was a render that dropped them.
    """
    subject = _resolved(assistant, SARAH_EMAIL)
    own = assistant.result(
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.COMMUNICATION_PREFERENCE,
            statement="Sarah Synthetic prefers Teams messages.",
            idempotency_key="promoted-vs-note-0001",
        )
    )["memory_id"]
    promoted = _a_promoted_assertion(
        assistant.work_engine, subject, "Sarah Synthetic asked for written closeout updates."
    )

    memories = assistant.result(ListRelationshipMemories(entity_id=subject))["memories"]
    assert isinstance(memories, list)
    by_id = {str(entry["memory_id"]): entry for entry in memories}
    assert set(by_id) == {str(own), promoted}
    assert {entry["kind"] for entry in memories} == {MemoryKind.COMMUNICATION_PREFERENCE.value}
    assert {entry["pinned"] for entry in memories} == {False}

    assert by_id[promoted]["authority"] == MemoryAuthority.SOURCE_BACKED_ASSERTION.value
    assert by_id[str(own)]["authority"] == MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE.value
    assert by_id[promoted]["authority"] != by_id[str(own)]["authority"]


@pytest.mark.database
def test_remember_johns_birthday_is_april_seventeenth(assistant: _Assistant) -> None:
    """Turn 3: an important date with no year, because none was said.

    The year is the field a model is most tempted to fill in. It is absent from
    the request and absent from what was stored, and the precision says so.
    """
    subject = _resolved(assistant, JOHN_EMAIL)
    assistant.result(
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.IMPORTANT_DATE,
            statement="John Synthetic's birthday is April 17.",
            structured_value={
                "month": 4,
                "day": 17,
                "precision": "month_day",
                "recurrence": "annual",
            },
            idempotency_key="turn-three-0001",
        )
    )
    listed = assistant.result(ListRelationshipMemories(entity_id=subject))
    memories = listed["memories"]
    assert isinstance(memories, list)
    detail = assistant.result(GetRelationshipMemory(memory_id=str(memories[0]["memory_id"])))
    stored = detail["memory"]["current_version"]["structured_value"]
    assert stored["schema"] == "relationship_memory.important_date.v1"
    assert "year" not in stored["value"]
    assert stored["value"]["precision"] == "month_day"


@pytest.mark.database
def test_john_prefers_teams_now_not_phone(assistant: _Assistant) -> None:
    """Turn 4: read the version, then revise with exactly the version that was read.

    `expected_version` is the aggregate counter the listing published. A model
    that guessed at it, or reused the version *number*, would be refused — which
    is the point: a blind correction cannot overwrite what it did not see.
    """
    subject = _resolved(assistant, JOHN_EMAIL)
    assistant.result(
        CreateRelationshipMemory(
            entity_id=subject,
            kind=MemoryKind.COMMUNICATION_PREFERENCE,
            statement="John Synthetic prefers phone calls.",
            idempotency_key="turn-four-0001",
        )
    )
    listed = assistant.result(ListRelationshipMemories(entity_id=subject))
    memories = listed["memories"]
    assert isinstance(memories, list)
    entry = memories[0]
    revised = assistant.result(
        ReviseRelationshipMemory(
            memory_id=str(entry["memory_id"]),
            expected_version=int(entry["version"]),
            statement="John Synthetic prefers Teams messages now, not phone calls.",
            correction_reason="the preference changed",
            idempotency_key="turn-four-0002",
        )
    )
    assert revised["version_number"] == 2
    assert revised["version"] == int(entry["version"]) + 1
    stale = assistant.send(
        ReviseRelationshipMemory(
            memory_id=str(entry["memory_id"]),
            expected_version=int(entry["version"]),
            statement="A third synthetic wording.",
            idempotency_key="turn-four-0003",
        )
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT


@pytest.mark.database
def test_show_me_the_history_of_that_note(assistant: _Assistant) -> None:
    """Turn 5: both wordings, oldest first, with what superseded what."""
    subject = _resolved(assistant, JOHN_EMAIL)
    created = assistant.result(
        CreateRelationshipMemory(
            entity_id=subject,
            statement="John Synthetic prefers phone calls.",
            idempotency_key="turn-five-0001",
        )
    )
    assistant.result(
        ReviseRelationshipMemory(
            memory_id=str(created["memory_id"]),
            expected_version=int(created["version"]),
            statement="John Synthetic prefers Teams messages now, not phone calls.",
            idempotency_key="turn-five-0002",
        )
    )
    history = assistant.result(GetRelationshipMemoryHistory(memory_id=str(created["memory_id"])))
    versions = history["versions"]
    assert isinstance(versions, list)
    assert [entry["version_number"] for entry in versions] == [1, 2]
    assert versions[0]["statement"] == "John Synthetic prefers phone calls."
    assert versions[1]["statement"] == (
        "John Synthetic prefers Teams messages now, not phone calls."
    )
    assert versions[0]["prior_version_id"] is None
    assert versions[1]["prior_version_id"] == versions[0]["memory_version_id"]


@pytest.mark.database
def test_archive_that_note_and_then_restore_it(assistant: _Assistant) -> None:
    """Turn 6: withdrawal is reversible, and there is no capability that deletes."""
    subject = _resolved(assistant, SARAH_EMAIL)
    created = assistant.result(
        CreateRelationshipMemory(
            entity_id=subject,
            statement="Sarah Synthetic prefers Teams messages.",
            idempotency_key="turn-six-0001",
        )
    )
    archived = assistant.result(
        ArchiveRelationshipMemory(
            memory_id=str(created["memory_id"]),
            expected_version=int(created["version"]),
            idempotency_key="turn-six-0002",
        )
    )
    assert archived["lifecycle"] == MemoryLifecycle.ARCHIVED.value
    after_archive = assistant.result(ListRelationshipMemories(entity_id=subject))
    assert after_archive["memories"] == []
    restored = assistant.result(
        RestoreRelationshipMemory(
            memory_id=str(created["memory_id"]),
            expected_version=int(archived["version"]),
            idempotency_key="turn-six-0003",
        )
    )
    assert restored["lifecycle"] == MemoryLifecycle.ACTIVE.value
    after_restore = assistant.result(ListRelationshipMemories(entity_id=subject))
    memories = after_restore["memories"]
    assert isinstance(memories, list)
    assert [entry["memory_id"] for entry in memories] == [created["memory_id"]]
    # The lifecycle moved twice and the statement never did.
    assert [entry["current_version_number"] for entry in memories] == [1]


@pytest.mark.database
def test_an_ambiguous_person_is_not_guessed_and_a_name_is_never_an_entity_id(
    assistant: _Assistant,
) -> None:
    """Turn 7: the refusal the whole plane depends on.

    A wrong identity contaminates every record joined to it afterwards, so an
    ambiguous reference returns both candidates and no chosen one — and the write
    path will not accept the name itself in place of the identifier it could not
    produce, which is the shortcut a model under pressure would otherwise take.
    """
    # A memory that *is* written first, so the emptiness asserted at the end is
    # about these two subjects rather than about an unpopulated table.
    written = assistant.result(
        CreateRelationshipMemory(
            entity_id=SARAH,
            statement="Sarah Synthetic prefers Teams messages.",
            idempotency_key="turn-seven-0001",
        )
    )
    assert written["created"] is True

    resolution = assistant.result(ResolveEntity(reference=SHARED_NAME))["resolution"]
    assert resolution["outcome"] == ResolutionOutcome.AMBIGUOUS.value
    assert resolution["entity_id"] is None
    assert sorted(candidate["entity_id"] for candidate in resolution["candidates"]) == sorted(
        [SHARED_ONE, SHARED_TWO]
    )

    # And a *unique* name is ambiguous too, which is the stronger half: there is
    # no number of name matches at which a name becomes an identifier, so being
    # the only Sarah is not evidence that this Sarah is the one meant.
    lone = assistant.result(ResolveEntity(reference=SARAH_NAME))["resolution"]
    assert lone["outcome"] == ResolutionOutcome.AMBIGUOUS.value
    assert lone["entity_id"] is None
    assert [candidate["entity_id"] for candidate in lone["candidates"]] == [SARAH]

    # The shortcut a model under pressure takes: send the name where the
    # identifier goes. Refused by the command, and refused again on the wire.
    with pytest.raises(InvalidRequestError):
        CreateRelationshipMemory(
            entity_id=SHARED_NAME,
            statement="A synthetic note about whoever that was.",
            idempotency_key="turn-seven-0002",
        )
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.RELATIONSHIP_MEMORY_CREATE.value,
            _envelope(
                Capability.RELATIONSHIP_MEMORY_CREATE,
                {
                    "entity_id": SHARED_NAME,
                    "statement": "A synthetic note about whoever that was.",
                    "idempotency_key": "turn-seven-0003",
                },
            ),
        )

    assert assistant.result(ListRelationshipMemories(entity_id=SHARED_ONE))["memories"] == []
    assert assistant.result(ListRelationshipMemories(entity_id=SHARED_TWO))["memories"] == []
    assert assistant.result(ListRelationshipMemories(entity_id=SARAH))["memories"] != []


@pytest.mark.database
def test_a_read_purpose_cannot_invoke_a_write_through_the_service(
    assistant: _Assistant,
) -> None:
    """The purpose split, measured at the entry point rather than in the table."""
    denied = assistant.send(
        CreateRelationshipMemory(
            entity_id=SARAH,
            statement="A synthetic note nobody is allowed to write this way.",
            idempotency_key="wrong-purpose-0001",
        ),
        purpose=Purpose.RELATIONSHIP_MEMORY_READ,
    )
    assert denied.error is not None
    assert denied.error.code is ErrorCode.DENIED
    with assistant.work_engine.connect() as connection:
        written = int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.relationship_memories")
            ).scalar_one()
        )
    assert written == 0


# --- context scope, and a subject that was merged away ---------------------------


@pytest.mark.database
def test_a_context_scoped_memory_is_not_returned_when_another_context_is_asked_for(
    assistant: _Assistant,
) -> None:
    """`RM-AC-012`: a note that is true *in a context* is not offered as true generally.

    Two notes on one subject, identical in kind, lifecycle and authority and
    differing only in whether they are linked to a context entity. Asked for the
    context, the listing returns the linked one alone; asked for a context the
    subject has no link to, it returns nothing; asked for no context at all, it
    returns both. The third read is what makes the first two mean something —
    without it, a filter that returned an empty page for every argument would
    satisfy the exclusion and disclose nothing.

    Driven through `ApplicationService.invoke`, because the criterion is about
    what a caller is *presented* with. The repository's own filter is proved in
    `tests/database/test_relationship_memory_repository.py`; this is the half
    that says the capability surface carries the scope through rather than
    dropping it and answering the unscoped page — which is what a listing that
    silently ignored `context_entity_id` would look like, and is exactly how a
    context-bound note would come to be read as a general fact.
    """
    scoped = assistant.result(
        CreateRelationshipMemory(
            entity_id=SARAH,
            statement="Sarah Synthetic chairs the Monday review for this project.",
            context_links=({"target_type": "entity", "target_id": JOHN, "role": "related_to"},),
            idempotency_key="context-scope-0001",
        )
    )
    general = assistant.result(
        CreateRelationshipMemory(
            entity_id=SARAH,
            statement="Sarah Synthetic prefers Teams messages.",
            idempotency_key="context-scope-0002",
        )
    )

    def _listed(context_entity_id: str | None) -> list[str]:
        answer = assistant.result(
            ListRelationshipMemories(entity_id=SARAH, context_entity_id=context_entity_id)
        )
        memories = answer["memories"]
        assert isinstance(memories, list)
        return sorted(str(entry["memory_id"]) for entry in memories)

    assert _listed(JOHN) == [str(scoped["memory_id"])]
    assert _listed(SHARED_ONE) == []
    assert _listed(None) == sorted([str(scoped["memory_id"]), str(general["memory_id"])])


@pytest.mark.database
def test_a_get_tells_the_caller_when_the_subject_has_been_merged_away(
    assistant: _Assistant,
) -> None:
    """`relationship_memory.get` names the survivor, and only once there is one.

    A memory keeps naming the identity it was written about; a merge does not
    rewrite it. So a caller reading a note whose subject has since been merged
    away is holding an identifier that no longer names the current person, and
    the only thing standing between that and a confident wrong answer is
    `canonical_subject_entity_id`. It is committed in
    `docs/specs/relationship-memory-v0.1.md` section 7 and had no test.

    Both states are asserted on one memory, before and after the merge, because
    the field is *absent* rather than null while the subject is current — one
    spelling, one meaning — and a view that emitted it unconditionally would pass
    a test that only looked at the merged case.
    """
    created = assistant.result(
        CreateRelationshipMemory(
            entity_id=SHARED_TWO,
            statement="Robin Synthetic keeps the north dock roster.",
            idempotency_key="merged-subject-0001",
        )
    )
    memory_id = str(created["memory_id"])

    def _read() -> Mapping[str, Any]:
        answer = assistant.result(GetRelationshipMemory(memory_id=memory_id))["memory"]
        assert isinstance(answer, Mapping)
        return answer

    current = _read()
    assert current["subject_entity_id"] == SHARED_TWO
    assert "canonical_subject_entity_id" not in current

    with assistant.work_engine.begin() as connection:
        SqlEntityRepository(connection).redirect_entity(PRINCIPAL, SHARED_TWO, SHARED_ONE)

    merged = _read()
    # The note still names the identity it was written about; what changed is
    # that the answer now says where that identity went.
    assert merged["subject_entity_id"] == SHARED_TWO
    assert merged["canonical_subject_entity_id"] == SHARED_ONE
