"""What `entities.observe`, `entities.observations.list` and the resolve capability publish.

Three claims, and they are about the *contract* rather than about the rules the
unit suites hold:

* the names are exactly the three the Relationship Intelligence contract freezes,
  and each is reachable, purposed and classified the way that contract says;
* the MCP schema each publishes is derived from its command — closed
  (`additionalProperties: false`), with every required field required and every
  closed vocabulary published as an `enum`, so a model calling the tool sees the
  vocabulary rather than guessing at it;
* every refusal this surface can produce is one of the eleven public
  `ErrorCode` members carrying a pre-categorised `safe_details` token, and no
  refusal anywhere on the surface carries the text a source produced.

The last one is the reason this file exists rather than being folded into the
capability suite: `observed_value` is the most sensitive request field on this
plane, and an error body is where a rejected value most easily ends up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.application.commands import (
    ListEntityObservations,
    ObserveEntityMention,
    ResolveUnresolvedMention,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityObservation,
    ObservationAuthority,
    ObservationKind,
    ResolutionDisposition,
)
from my_pa.domain.relationship.normalization import normalize_name

ALICE = "ent_aaaa0001aaaa0001"
MENTION = "eobs_aaaa0001aaaa01"
#: A second mention whose observed value is the bare name the staged entity
#: carries, so the resolver actually matches it. `MENTION` deliberately does
#: not: its value is a mail envelope, and `normalize_name` keeps the local
#: part and the domain, so it matches nothing -- which is why the leak
#: assertions use that one and the resolution assertions use this one.
PLAIN_MENTION = "eobs_bbbb0002bbbb02"
CAPTURE = "cap_aaaa0001aaaa0001"
CAPTURE_VERSION = "capver_aaaa0001aaaa01"
#: Before the scene clock. An observation is a claim about a moment that has
#: already happened, and a request naming a future one is refused rather than
#: recorded -- see `test_an_observation_may_not_be_observed_after_it_is_recorded`.
WHEN = datetime(2026, 8, 1, 12, tzinfo=UTC)

#: A name with a mail envelope around it, and the value every refusal below is
#: searched for. `normalize_name` removes no content, so the normalized form
#: carries the local part and the domain too — both are searched.
ENVELOPE: Final = "Alice Chen <a.chen@northwind.test>"

THE_THREE: Final = (
    Capability.ENTITIES_OBSERVATIONS_LIST,
    Capability.ENTITIES_OBSERVE,
    Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
)


@pytest.fixture
def staged(scene: Scene) -> Scene:
    """One entity, and one mention nothing has placed."""
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.create(
            principal_id,
            Entity(
                entity_id=ALICE,
                principal_id=principal_id,
                entity_type=EntityType.PERSON,
                canonical_name=normalize_name("Alice Chen"),
                display_name="Alice Chen",
                status=EntityStatus.ACTIVE,
                created_at=WHEN,
                updated_at=WHEN,
                version=1,
            ),
        )
        unit_of_work.entities.record_observation(
            principal_id,
            EntityObservation(
                observation_id=MENTION,
                principal_id=principal_id,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value=ENVELOPE,
                normalized_value=normalize_name(ENVELOPE),
                mention_display_name="Alice Chen",
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                source_version_id="ver_aaaa0001aaaa0001",
                observed_at=WHEN,
                recorded_at=WHEN,
            ),
        )
        unit_of_work.entities.record_observation(
            principal_id,
            EntityObservation(
                observation_id=PLAIN_MENTION,
                principal_id=principal_id,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value="Alice Chen",
                normalized_value=normalize_name("Alice Chen"),
                mention_display_name="Alice Chen",
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                source_version_id="ver_bbbb0002bbbb0002",
                observed_at=WHEN,
                recorded_at=WHEN,
            ),
        )
    return scene


def _invoke(scene: Scene, capability: Capability, command: object) -> dict[str, Any]:
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    return envelope.to_canonical_dict()


def an_observe(**overrides: object) -> ObserveEntityMention:
    fields: dict[str, object] = {
        "kind": ObservationKind.USER_STATEMENT,
        "authority": ObservationAuthority.USER_AUTHORED_STATEMENT,
        "observed_value": ENVELOPE,
        "observed_at": WHEN,
        "idempotency_key": "surface-observe-0001",
        "capture_id": CAPTURE,
        "capture_version_id": CAPTURE_VERSION,
    }
    fields.update(overrides)
    return ObserveEntityMention(**fields)  # type: ignore[arg-type]


def a_resolve(**overrides: object) -> ResolveUnresolvedMention:
    fields: dict[str, object] = {
        "observation_id": MENTION,
        "expected_resolution_version": 0,
        "disposition": ResolutionDisposition.DEFER,
        "idempotency_key": "surface-resolve-0001",
        "reason": "there is not enough identity evidence yet",
    }
    fields.update(overrides)
    return ResolveUnresolvedMention(**fields)  # type: ignore[arg-type]


# --- the names ----------------------------------------------------------------


def test_the_three_names_are_exactly_what_the_contract_freezes() -> None:
    """Spelled out, because a rename is a contract break rather than a refactor."""
    assert [capability.value for capability in THE_THREE] == [
        "entities.observations.list",
        "entities.observe",
        "entities.unresolved_mentions.resolve",
    ]


def test_each_carries_exactly_one_purpose_and_the_writes_do_not_share_it() -> None:
    assert permitted_purposes(Capability.ENTITIES_OBSERVATIONS_LIST) == frozenset(
        {Purpose.ENTITY_READ}
    )
    assert permitted_purposes(Capability.ENTITIES_OBSERVE) == frozenset(
        {Purpose.ENTITY_OBSERVATION_INGEST}
    )
    assert permitted_purposes(Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE) == frozenset(
        {Purpose.ENTITY_AUTHORING}
    )


# --- the published schema -------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "required"),
    [
        (ListEntityObservations, []),
        (
            ObserveEntityMention,
            ["kind", "authority", "observed_value", "observed_at", "idempotency_key"],
        ),
        (
            ResolveUnresolvedMention,
            [
                "observation_id",
                "expected_resolution_version",
                "disposition",
                "idempotency_key",
            ],
        ),
    ],
    ids=lambda value: getattr(value, "__name__", ""),
)
def test_the_schema_is_closed_and_requires_what_the_command_requires(
    command: type, required: list[str]
) -> None:
    """Derived from the dataclass, so a field added to one arrives in the schema.

    `additionalProperties: false` is what makes a caller-supplied
    `principal_id`, `observation_id` or `recorded_at` a refusal rather than an
    ignored key — which is the whole of "the server owns those fields".
    """
    schema = payload_schema_for(command)
    assert schema["additionalProperties"] is False
    assert schema["required"] == required
    assert "principal_id" not in schema["properties"]
    assert "recorded_at" not in schema["properties"]
    assert "normalized_value" not in schema["properties"]


def test_the_closed_vocabularies_are_published_as_enums() -> None:
    """A model calling the tool sees the members instead of guessing at them."""
    observe = payload_schema_for(ObserveEntityMention)["properties"]
    assert observe["kind"]["enum"] == [member.value for member in ObservationKind]
    assert observe["authority"]["enum"] == [member.value for member in ObservationAuthority]
    resolve = payload_schema_for(ResolveUnresolvedMention)["properties"]
    assert resolve["disposition"]["enum"] == [member.value for member in ResolutionDisposition]


def test_the_observe_schema_documents_which_authority_a_model_may_not_claim() -> None:
    """The description is the only place a caller learns the rule before it fires."""
    described = payload_schema_for(ObserveEntityMention)["properties"]["authority"]["description"]
    assert "model" in described
    assert "propose" in described


# --- the answers ----------------------------------------------------------------


def test_observe_answers_a_receipt_and_never_the_observed_text(staged: Scene) -> None:
    body = _invoke(staged, Capability.ENTITIES_OBSERVE, an_observe())
    assert body["error"] is None
    result = body["result"]
    assert set(result) == {
        "observation_id",
        "kind",
        "authority",
        "origin",
        "state",
        "resolution_version",
        "entity_id",
        "recorded_at",
        "idempotency_key",
        "created",
        # The completion contract requires every mutation result to carry a
        # receipt and the audit reference it was written under, and this plane's
        # receipt is the `entity_mutation_events` row -- an `emut_…`, not a
        # second identifier and not the observation's own.
        "receipt_id",
        "audit_id",
    }
    assert result["receipt_id"].startswith("emut_")
    assert result["receipt_id"] != result["observation_id"]
    assert result["audit_id"].startswith("audit_")
    rendered = str(body)
    assert ENVELOPE not in rendered
    assert normalize_name(ENVELOPE) not in rendered


def test_the_observation_log_publishes_neither_value_the_source_produced(
    staged: Scene,
) -> None:
    body = _invoke(staged, Capability.ENTITIES_OBSERVATIONS_LIST, ListEntityObservations())
    assert body["error"] is None
    published = next(
        row for row in body["result"]["observations"] if row["observation_id"] == MENTION
    )
    assert "observed_value" not in published
    assert "normalized_value" not in published
    assert published["mention_display_name"] == "Alice Chen"
    # The version a decision has to state, which the queue's own view omits.
    assert published["resolution_version"] == 0
    assert ENVELOPE not in str(body)
    assert normalize_name(ENVELOPE) not in str(body)


def test_resolve_answers_the_decision_it_recorded(staged: Scene) -> None:
    body = _invoke(staged, Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE, a_resolve())
    assert body["error"] is None
    result = body["result"]
    assert result["disposition"] == "defer"
    assert result["resolution_version"] == 1
    assert result["entity_id"] is None
    assert result["created"] is True


# --- the stable problems ----------------------------------------------------------


def test_a_stale_resolution_version_is_a_conflict_naming_its_own_field(
    staged: Scene,
) -> None:
    """`expected_resolution_version`, and not `expected_version`.

    A mention carries a resolution version and an entity carries an aggregate
    one. A caller told the wrong field would refresh the wrong record.
    """
    _invoke(staged, Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE, a_resolve())
    body = _invoke(
        staged,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        a_resolve(idempotency_key="surface-resolve-0002"),
    )
    assert body["error"]["code"] == ErrorCode.CONFLICT.value
    assert body["error"]["safe_details"] == ["expected_resolution_version"]


def test_one_key_bound_to_a_different_request_is_an_idempotency_conflict(
    staged: Scene,
) -> None:
    _invoke(staged, Capability.ENTITIES_OBSERVE, an_observe())
    body = _invoke(staged, Capability.ENTITIES_OBSERVE, an_observe(observed_value="Someone Else"))
    assert body["error"]["code"] == ErrorCode.CONFLICT.value
    assert body["error"]["safe_details"] == ["idempotency_key"]


def test_an_authority_the_origin_does_not_support_is_an_invalid_request(
    staged: Scene,
) -> None:
    body = _invoke(
        staged,
        Capability.ENTITIES_OBSERVE,
        an_observe(authority=ObservationAuthority.SOURCE_OBSERVATION),
    )
    assert body["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert body["error"]["safe_details"] == ["observation_authority"]


def test_creating_a_second_record_for_a_matched_reference_is_ambiguous(
    staged: Scene,
) -> None:
    """`ambiguous_request` rather than `conflict`: somebody has to say which."""
    body = _invoke(
        staged,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        a_resolve(
            observation_id=PLAIN_MENTION,
            disposition=ResolutionDisposition.CREATE_NEW,
            entity_type=EntityType.PERSON,
            canonical_name="Alice Chen",
            reason=None,
        ),
    )
    assert body["error"]["code"] == ErrorCode.AMBIGUOUS_REQUEST.value
    assert body["error"]["safe_details"] == ["ambiguous_identity"]


def test_a_mention_of_another_principal_is_not_found_and_not_denied(
    staged: Scene,
) -> None:
    """A foreign record is indistinguishable from an absent one."""
    body = _invoke(
        staged,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        a_resolve(observation_id="eobs_ffff0009ffff09"),
    )
    assert body["error"]["code"] == ErrorCode.NOT_FOUND.value
    assert body["error"]["safe_details"] == ["observation_id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"observed_value": ENVELOPE + "   "},
        {"authority": ObservationAuthority.SOURCE_OBSERVATION},
        {"mention_display_name": " " + ENVELOPE + " "},
        {"observed_value": ENVELOPE * 40},
    ],
    ids=["padded-value", "unsupported-authority", "padded-display-name", "too-long"],
)
def test_no_refusal_carries_the_value_it_refused(
    staged: Scene, overrides: dict[str, object]
) -> None:
    """The one field on this plane whose value must never reach an error body.

    `safe_details` is a closed token vocabulary and `message` is a fixed
    sentence, so this holds structurally — and it is asserted anyway, because
    the structural argument is exactly the one that was true of
    `entities.unresolved_mentions` while it published `normalized_value`.

    The construction is inside the `try` deliberately: two of these four are
    refused by `__post_init__` before any handler runs, and a refusal raised
    from a constructor is as capable of carrying the value as one raised from a
    use case.
    """
    try:
        body = str(_invoke(staged, Capability.ENTITIES_OBSERVE, an_observe(**overrides)))
    except Exception as refused:
        body = f"{refused!r}"
    assert ENVELOPE not in body
    assert "northwind" not in body
    assert "a.chen" not in body


def test_an_observation_may_not_be_observed_after_it_is_recorded(staged: Scene) -> None:
    """A mistyped date is `invalid_request`, not `internal_error`.

    Found by this file: the record's own `__post_init__` refuses the ordering
    with a bare `ValueError`, which crosses the handler boundary as
    `internal_error` — "this is our fault, retrying will not help" — for a
    request that named a moment in the future and could simply be corrected.
    The layer holding the server clock refuses it now, naming the field.
    """
    body = _invoke(
        staged,
        Capability.ENTITIES_OBSERVE,
        an_observe(observed_at=datetime(2030, 1, 1, tzinfo=UTC)),
    )
    assert body["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert body["error"]["safe_details"] == ["observed_at"]
