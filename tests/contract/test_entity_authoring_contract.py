"""The public contract of the entity plane's authoring half (`WP-RI-A-02`).

What a caller sees: the names, the shape of a receipt, the shape of a refusal,
and the fields a payload may and may not carry. `tests/unit/test_entity_authoring.py`
proves what each write *does*; this proves what a caller is told about it.

**The names are frozen here rather than derived.** Every other assertion in this
file reads `Capability`, so a rename would move them all together and none would
notice. The literal set is what makes a rename a visible edit: these strings are
in a completion contract, and a caller holding a grant for `entities.aliases.add`
does not get to discover that it is now called something else.

**The refusal tokens are the contract's own.** `conflict` is one public code
covering a stale version, a spent idempotency key, a duplicated fact and an
address two entities claim -- four different next actions. The token is what
separates them, so each is asserted by name and each is asserted to be
*different* from the field-name token that reports the same field being
malformed.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.conftest import FakeProviders, Scene, World, build_service, metadata_for

from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    AddEntityAlias,
    ArchiveEntity,
    BindEntityIdentifier,
    CreateEntity,
    ListEntityAliases,
    ListEntityIdentifiers,
    RestoreEntity,
    RetireEntityAlias,
    RetireEntityIdentifier,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
    UpdateEntity,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Entity,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.source.registry import issue_identifier

#: The ten writes and two reads this package adds, spelled out. See the module
#: docstring for why they are literals.
AUTHORING_NAMES: Final[frozenset[str]] = frozenset(
    {
        "entities.identifiers.list",
        "entities.aliases.list",
        "entities.create",
        "entities.update",
        "entities.archive",
        "entities.restore",
        "entities.identifiers.bind",
        "entities.identifiers.retire",
        "entities.identifiers.supersede",
        "entities.aliases.add",
        "entities.aliases.retire",
        "entities.aliases.supersede",
    }
)

WRITE_NAMES: Final[frozenset[str]] = AUTHORING_NAMES - {
    "entities.identifiers.list",
    "entities.aliases.list",
}

MINE: Final = "prn_aaaa0001aaaa0001aaaa0001"


def test_every_name_this_package_adds_exists_exactly_as_written() -> None:
    served = {capability.value for capability in Capability}
    assert served >= AUTHORING_NAMES


def test_the_reads_take_the_read_purpose_and_the_writes_take_the_write_one() -> None:
    """One mapping, checked from the outside, because policy denies an unmapped name."""
    for capability in Capability:
        if capability.value not in AUTHORING_NAMES:
            continue
        writes = capability.value in WRITE_NAMES
        expected = Purpose.ENTITY_AUTHORING if writes else Purpose.ENTITY_READ
        assert permitted_purposes(capability) == frozenset({expected}), capability.value


def test_every_one_of_them_publishes_a_closed_tool_schema() -> None:
    """`additionalProperties: false`, so an unknown field is refused rather than dropped.

    A dropped field is how a caller comes to believe it set something it did not
    -- and on this plane the field it believed it set could be the address a
    person's mail resolves to.
    """
    published = {tool.name: tool for tool in TOOLS if tool.name in AUTHORING_NAMES}
    assert set(published) == AUTHORING_NAMES
    for name, tool in published.items():
        schema = tool.input_schema
        assert schema["additionalProperties"] is False, name
        payload = schema["properties"]["payload"]
        assert payload["additionalProperties"] is False, name
        assert tool.description, name


def test_no_write_publishes_a_field_the_server_owns() -> None:
    """The absence that makes "a caller cannot self-assert this" structural.

    Not a validation rule -- a field that can be sent is a field a later change
    can start honouring -- so the assertion is that the schema has no such
    property at all.
    """
    forbidden = {
        "principal_id",
        "version",
        "authority",
        "actor_class",
        "classification",
        "canonical_name_normalized",
        "normalized_value",
        "created_at",
        "updated_at",
        "superseded_by_entity_id",
        "superseded_by_identifier_id",
        "superseded_by_alias_id",
        "verified",
        "archived_from_status",
        "receipt_id",
        "audit_id",
    }
    for tool in TOOLS:
        if tool.name not in WRITE_NAMES:
            continue
        published = set(tool.input_schema["properties"]["payload"]["properties"])
        assert not published & forbidden, f"{tool.name} publishes {sorted(published & forbidden)}"


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        (
            "entities.create",
            {
                "entity_type": "person",
                "display_name": "Sarah Chen",
                "aliases": [{"alias_type": "nickname", "display_value": "Sar"}],
                "identifiers": [{"namespace": "email", "display_value": "s@example.invalid"}],
                "idempotency_key": "contract-create",
            },
        ),
        (
            "entities.identifiers.list",
            {"entity_id": "ent_aaaa0001aaaa0001", "states": ["active"]},
        ),
        (
            "entities.aliases.list",
            {"entity_id": "ent_aaaa0001aaaa0001", "alias_types": ["nickname"]},
        ),
    ],
)
def test_a_wire_payload_becomes_the_command_the_handler_takes(
    capability: str, payload: dict[str, object]
) -> None:
    """Shape conversion only: JSON has no enum and no tuple."""
    _, command = normalize(
        capability,
        {
            "request_id": "req-contract-001",
            "purpose": sorted(permitted_purposes(Capability(capability)))[0].value,
            "contract_version": "v1",
            "principal_id": MINE,
            "requested_at": "2026-08-20T12:00:00Z",
            "payload": payload,
        },
    )
    assert command.capability is Capability(capability)


def test_an_unknown_field_is_refused_rather_than_dropped() -> None:
    with pytest.raises(InvalidRequestError):
        normalize(
            "entities.archive",
            {
                "request_id": "req-contract-002",
                "purpose": "entity_authoring",
                "contract_version": "v1",
                "principal_id": MINE,
                "requested_at": "2026-08-20T12:00:00Z",
                "payload": {
                    "entity_id": "ent_aaaa0001aaaa0001",
                    "expected_version": 1,
                    "reason": "A synthetic withdrawal.",
                    "idempotency_key": "contract-archive",
                    "principal_id": "prn_aaaa0001aaaa0001aaaa0001",
                },
            },
        )


def test_an_update_that_names_nothing_to_change_is_refused() -> None:
    """At least one of display name, matched name and status, or the request says nothing."""
    with pytest.raises(InvalidRequestError) as refusal:
        UpdateEntity(
            entity_id=issue_identifier(IdKind.ENTITY),
            expected_version=1,
            reason="A synthetic correction.",
            idempotency_key="contract-update",
        )
    assert refusal.value.safe_details == (SafeDetail.SELECTOR,)


@pytest.mark.parametrize(
    ("command", "detail"),
    [
        ("archive_without_reason", SafeDetail.REASON),
        ("bind_with_a_bad_namespace", SafeDetail.NAMESPACE),
        ("alias_with_an_empty_state_filter", SafeDetail.STATES),
        ("bind_with_unusable_evidence", SafeDetail.EVIDENCE),
    ],
)
def test_a_malformed_request_names_the_field_and_never_the_value(
    command: str, detail: SafeDetail
) -> None:
    """Each refusal carries a token, and the token names a field rather than a value."""
    entity_id = issue_identifier(IdKind.ENTITY)
    attempts = {
        "archive_without_reason": lambda: ArchiveEntity(
            entity_id=entity_id,
            expected_version=1,
            reason=None,  # type: ignore[arg-type]
            idempotency_key="contract-a",
        ),
        "bind_with_a_bad_namespace": lambda: BindEntityIdentifier(
            entity_id=entity_id,
            expected_version=1,
            namespace="not_a_namespace",  # type: ignore[arg-type]
            display_value="s@example.invalid",
            idempotency_key="contract-b",
        ),
        "alias_with_an_empty_state_filter": lambda: ListEntityAliases(
            entity_id=entity_id, states=()
        ),
        "bind_with_unusable_evidence": lambda: BindEntityIdentifier(
            entity_id=entity_id,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="s@example.invalid",
            evidence=("not-an-identifier",),
            idempotency_key="contract-c",
        ),
    }
    with pytest.raises(InvalidRequestError) as refusal:
        attempts[command]()
    assert refusal.value.safe_details == (detail,)


# --- what a successful mutation answers with ---------------------------------


@pytest.fixture
def staged() -> tuple[Scene, str, str, str]:
    """One entity with one active binding and one active alias, and a service over it."""
    from datetime import UTC, datetime

    from tests.conftest import FakeUnitOfWork, operator

    world = World()
    principal = operator(MINE)
    when = datetime(2026, 8, 1, 12, tzinfo=UTC)
    entities = FakeUnitOfWork(world).entities
    entity = entities.create(
        MINE,
        Entity(
            entity_id=issue_identifier(IdKind.ENTITY),
            principal_id=MINE,
            entity_type=EntityType.PERSON,
            canonical_name=normalize_name("Sarah Chen"),
            display_name="Sarah Chen",
            status=EntityStatus.ACTIVE,
            created_at=when,
            updated_at=when,
            version=1,
        ),
    )
    identifier_id = issue_identifier(IdKind.EXTERNAL_IDENTIFIER)
    entities.bind_identifier(
        MINE,
        entity.entity_id,
        ExternalIdentifier(
            identifier_id=identifier_id,
            entity_id=entity.entity_id,
            namespace=ExternalIdentifierNamespace.EMAIL,
            normalized_value=normalize_identifier(
                ExternalIdentifierNamespace.EMAIL, "sarah@example.invalid"
            ),
            display_value="sarah@example.invalid",
            principal_id=MINE,
        ),
    )
    alias_id = issue_identifier(IdKind.ENTITY_ALIAS)
    from my_pa.domain.relationship.entity import EntityAlias

    entities.record_alias(
        MINE,
        EntityAlias(
            alias_id=alias_id,
            entity_id=entity.entity_id,
            alias_type=AliasType.NICKNAME,
            normalized_value=normalize_name("Sar"),
            display_value="Sar",
            principal_id=MINE,
        ),
    )
    scene = Scene.__new__(Scene)
    scene.world = world  # type: ignore[attr-defined]
    scene.principal = principal  # type: ignore[attr-defined]
    return scene, entity.entity_id, identifier_id, alias_id


def _invoke(scene: Scene, capability: Capability, command: object) -> dict[str, object]:
    service = build_service(scene.world, FakeProviders(), relationship_intelligence_enabled=True)
    envelope = service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    return envelope.to_canonical_dict()


def test_a_successful_mutation_answers_with_the_whole_receipt(
    staged: tuple[Scene, str, str, str],
) -> None:
    """Every field the completion contract names, on one answer.

    Asserted as a set rather than field by field, because a receipt that dropped
    one would still satisfy every individual assertion about the rest.
    """
    scene, entity_id, _identifier_id, _alias_id = staged
    answer = _invoke(
        scene,
        Capability.ENTITIES_ALIASES_ADD,
        AddEntityAlias(
            entity_id=entity_id,
            expected_version=1,
            alias_type=AliasType.INITIALS,
            display_value="SC",
            idempotency_key="receipt-0001",
        ),
    )
    assert answer["error"] is None
    result = answer["result"]
    assert isinstance(result, dict)
    assert set(result) == {
        "record_id",
        "record_family",
        "entity_id",
        "entity_version",
        "lifecycle_state",
        "child_id",
        "child_version",
        "child_state",
        "superseded_ids",
        "evidence_refs",
        "receipt_id",
        "audit_id",
        "idempotent_replay",
        "canonical_entity_id",
    }
    assert result["entity_id"] == entity_id
    assert result["entity_version"] == 2
    assert result["record_family"] == "alias"
    assert result["lifecycle_state"] == "active"
    assert result["idempotent_replay"] is False


def test_a_replayed_write_says_so_rather_than_leaving_it_to_be_inferred(
    staged: tuple[Scene, str, str, str],
) -> None:
    """A client whose response was lost has to know whether its retry wrote anything.

    Comparing versions cannot answer that: a concurrent writer could have moved
    them either way.
    """
    scene, entity_id, _identifier_id, _alias_id = staged

    def send() -> dict[str, object]:
        return _invoke(
            scene,
            Capability.ENTITIES_ALIASES_ADD,
            AddEntityAlias(
                entity_id=entity_id,
                expected_version=1,
                alias_type=AliasType.INITIALS,
                display_value="SC",
                idempotency_key="receipt-replay",
            ),
        )

    first = send()
    second = send()
    assert first["result"]["idempotent_replay"] is False  # type: ignore[index]
    assert second["result"]["idempotent_replay"] is True  # type: ignore[index]
    assert second["result"]["record_id"] == first["result"]["record_id"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("case", "code", "detail"),
    [
        ("stale", "conflict", SafeDetail.STALE_VERSION),
        ("idempotency", "conflict", SafeDetail.IDEMPOTENCY_CONFLICT),
        ("duplicate", "conflict", SafeDetail.DUPLICATE_FACT),
        ("conflicted_identifier", "conflict", SafeDetail.CONFLICTED_IDENTIFIER),
        ("ambiguous", "ambiguous_request", SafeDetail.AMBIGUOUS_IDENTITY),
        ("evidence", "invalid_request", SafeDetail.EVIDENCE_INVALID),
        ("absent", "not_found", SafeDetail.ENTITY_ID),
    ],
)
def test_every_stable_outcome_answers_with_its_own_token(
    staged: tuple[Scene, str, str, str], case: str, code: str, detail: SafeDetail
) -> None:
    """The contract's codes, carried as details on the eleven public ones.

    Four of these are `conflict` and the token is the only thing that separates
    them -- a caller told `conflict` alone has to guess which of four different
    next actions applies.
    """
    scene, entity_id, _identifier, _alias_id = staged
    if case == "idempotency":
        _invoke(
            scene,
            Capability.ENTITIES_ARCHIVE,
            ArchiveEntity(
                entity_id=entity_id,
                expected_version=1,
                reason="A synthetic withdrawal.",
                idempotency_key="outcome-key",
            ),
        )
    attempts = {
        "stale": (
            Capability.ENTITIES_ARCHIVE,
            ArchiveEntity(
                entity_id=entity_id,
                expected_version=9,
                reason="A synthetic withdrawal.",
                idempotency_key="outcome-stale",
            ),
        ),
        "idempotency": (
            Capability.ENTITIES_ARCHIVE,
            ArchiveEntity(
                entity_id=entity_id,
                expected_version=2,
                reason="A different withdrawal.",
                idempotency_key="outcome-key",
            ),
        ),
        "duplicate": (
            Capability.ENTITIES_IDENTIFIERS_BIND,
            BindEntityIdentifier(
                entity_id=entity_id,
                expected_version=1,
                namespace=CallerNamespace.EMAIL,
                display_value="sarah@example.invalid",
                idempotency_key="outcome-duplicate",
            ),
        ),
        "conflicted_identifier": (
            Capability.ENTITIES_CREATE,
            CreateEntity(
                entity_type=EntityType.PERSON,
                display_name="Someone Else",
                identifiers=({"namespace": "email", "display_value": "sarah@example.invalid"},),
                idempotency_key="outcome-conflicted",
            ),
        ),
        "ambiguous": (
            Capability.ENTITIES_CREATE,
            CreateEntity(
                entity_type=EntityType.PERSON,
                display_name="Sarah Chen",
                idempotency_key="outcome-ambiguous",
            ),
        ),
        "evidence": (
            Capability.ENTITIES_ALIASES_ADD,
            AddEntityAlias(
                entity_id=entity_id,
                expected_version=1,
                alias_type=AliasType.INITIALS,
                display_value="SC",
                evidence=(issue_identifier(IdKind.SPAN),),
                idempotency_key="outcome-evidence",
            ),
        ),
        "absent": (
            Capability.ENTITIES_ARCHIVE,
            ArchiveEntity(
                entity_id=issue_identifier(IdKind.ENTITY),
                expected_version=1,
                reason="A synthetic withdrawal.",
                idempotency_key="outcome-absent",
            ),
        ),
    }
    capability, command = attempts[case]
    answer = _invoke(scene, capability, command)
    error = answer["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    assert error["safe_details"] == [detail.value]


def test_the_stale_and_malformed_version_tokens_are_different() -> None:
    """A caller's own correctable mistake must not read as a state it has to re-read."""
    assert SafeDetail.STALE_VERSION is not SafeDetail.EXPECTED_VERSION
    assert SafeDetail.IDEMPOTENCY_CONFLICT is not SafeDetail.IDEMPOTENCY_KEY


def test_a_bounded_page_discloses_its_bound_and_a_cursor(
    staged: tuple[Scene, str, str, str],
) -> None:
    """A truncated page that read as complete would be the wrong answer, not a short one."""
    scene, entity_id, _identifier_id, _alias_id = staged
    answer = _invoke(
        scene,
        Capability.ENTITIES_ALIASES_LIST,
        ListEntityAliases(entity_id=entity_id, states=(AliasState.ACTIVE,), page_size=1),
    )
    disclosure = answer["disclosure"]
    assert isinstance(disclosure, dict)
    assert disclosure["truncation"]["is_truncated"] is False  # type: ignore[index]
    assert answer["result"]["aliases"][0]["state"] == "active"  # type: ignore[index]
    # Every field a retire or supersede needs to be driven from is disclosed.
    row = answer["result"]["aliases"][0]  # type: ignore[index]
    assert {"alias_id", "version", "state"} <= set(row)


def test_an_identifier_listing_discloses_the_version_a_retire_needs(
    staged: tuple[Scene, str, str, str],
) -> None:
    scene, entity_id, identifier_id, _alias_id = staged
    answer = _invoke(
        scene,
        Capability.ENTITIES_IDENTIFIERS_LIST,
        ListEntityIdentifiers(entity_id=entity_id, states=(IdentifierState.ACTIVE,)),
    )
    rows = answer["result"]["identifiers"]  # type: ignore[index]
    assert [row["identifier_id"] for row in rows] == [identifier_id]
    assert rows[0]["version"] == 1
    assert rows[0]["state"] == "active"


def test_a_lifecycle_command_can_be_driven_from_what_a_listing_disclosed(
    staged: tuple[Scene, str, str, str],
) -> None:
    """The loop the two reads exist to close, end to end.

    A caller that can see a binding and cannot act on it has been shown a
    lifecycle it may not use; this drives the retire entirely from what the
    listing returned.
    """
    scene, entity_id, _identifier_id, _alias_id = staged
    listed = _invoke(
        scene,
        Capability.ENTITIES_IDENTIFIERS_LIST,
        ListEntityIdentifiers(entity_id=entity_id),
    )
    row = listed["result"]["identifiers"][0]  # type: ignore[index]
    retired = _invoke(
        scene,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        RetireEntityIdentifier(
            entity_id=entity_id,
            expected_version=1,
            identifier_id=row["identifier_id"],
            expected_identifier_version=row["version"],
            reason="They left.",
            idempotency_key="drive-retire",
        ),
    )
    assert retired["error"] is None
    assert retired["result"]["child_state"] == "retired"  # type: ignore[index]


def test_the_bindable_namespaces_are_the_stored_ones_minus_the_two_legacy_identities() -> None:
    """The one vocabulary a caller may state, and the two it may not.

    `legacy_relationship_person_id` and `legacy_relationship_organization_id`
    are the identities the WP-9 substrate issued, and an entity carrying one is
    asserting that it *is* that Person or Organization -- an identity join
    between two planes, which section 15.3 makes a governed merge with lineage
    behind it. A caller that could name one as a namespace would perform that
    merge through a field.

    Derived on both sides rather than listed once: every `CallerNamespace`
    member must name a real stored namespace, and the difference must be exactly
    the two legacy ones. A namespace renamed on one side and not the other
    reddens here rather than quietly becoming unbindable.
    """
    bindable = {member.namespace for member in CallerNamespace}
    assert bindable <= set(ExternalIdentifierNamespace)
    assert set(ExternalIdentifierNamespace) - bindable == {
        ExternalIdentifierNamespace.LEGACY_RELATIONSHIP_PERSON_ID,
        ExternalIdentifierNamespace.LEGACY_RELATIONSHIP_ORGANIZATION_ID,
    }


def test_no_write_publishes_a_namespace_it_would_refuse() -> None:
    """What the schema advertises is what the server admits.

    A check inside the command would publish nine values and refuse two of them,
    which teaches a model to try something the server will not do. The field's
    own type is what the schema is derived from, so the vocabulary is the gate.
    """
    published = {
        tool.name: tool.input_schema["properties"]["payload"]["properties"]["namespace"]["enum"]
        for tool in TOOLS
        if tool.name in {"entities.identifiers.bind", "entities.identifiers.supersede"}
    }
    assert len(published) == 2
    for name, values in published.items():
        assert set(values) == {member.value for member in CallerNamespace}, name


def test_a_legacy_identity_namespace_is_refused_at_the_command() -> None:
    """The gate, exercised rather than inferred from the schema."""
    with pytest.raises(InvalidRequestError) as refusal:
        normalize(
            "entities.identifiers.bind",
            {
                "request_id": "req-contract-003",
                "purpose": "entity_authoring",
                "contract_version": "v1",
                "principal_id": MINE,
                "requested_at": "2026-08-20T12:00:00Z",
                "payload": {
                    "entity_id": "ent_aaaa0001aaaa0001",
                    "expected_version": 1,
                    "namespace": "legacy_relationship_person_id",
                    "display_value": "per_aaaa0001aaaa0001",
                    "idempotency_key": "contract-legacy",
                },
            },
        )
    assert refusal.value.safe_details == (SafeDetail.NAMESPACE,)


def test_the_family_this_file_covers_is_every_command_the_package_added() -> None:
    """Anti-vacuity: a file that named eleven of twelve would read as coverage."""
    covered = {
        ListEntityIdentifiers,
        ListEntityAliases,
        CreateEntity,
        UpdateEntity,
        ArchiveEntity,
        RestoreEntity,
        BindEntityIdentifier,
        RetireEntityIdentifier,
        SupersedeEntityIdentifier,
        AddEntityAlias,
        RetireEntityAlias,
        SupersedeEntityAlias,
    }
    assert {command.capability.value for command in covered} == AUTHORING_NAMES
