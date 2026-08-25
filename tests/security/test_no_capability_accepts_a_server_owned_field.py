"""Server-owned request fields are refused on **every** capability, derived not listed.

`compose_remote_arguments` refuses a caller-supplied envelope field before it
resolves the capability, so the check is capability-independent by construction.
The existing sweep in `tests/unit/test_remote_request.py` says so for a
population it derives -- and then subtracts `KEYLESS_ENTITY_WRITES` from, which
is where Phase B's `entities.proposals.create`, `entities.merge.preview` and
`entities.merge` went. `relationship_memory.propose` was never in that
population at all: it derives from the `entities.` prefix. So every capability
this phase publishes is covered by the *schema* half of that module and by none
of the *runtime refusal* half.

A subtraction list is exactly the shape of hole this module exists to close.
The population here is `Capability` itself with nothing removed, so a capability
added by any later phase joins this sweep by existing. Operator §26 names the
fields; `SERVER_OWNED_REMOTE_FIELDS` and `REMOTE_OWNED_PAYLOAD_FIELDS` are the
repository's encoding of them, and both are read rather than restated.

Every case carries a control: the same request without the injected field is
composed successfully, so a refusal cannot be credited to a request that was
malformed for some other reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, get_args

import pytest

from my_pa.adapters.mcp.tools import input_schema_for
from my_pa.adapters.remote_request import (
    REMOTE_OWNED_PAYLOAD_FIELDS,
    SERVER_OWNED_REMOTE_FIELDS,
    compose_remote_arguments,
    is_server_replay_capability,
    remote_tool_schema,
)
from my_pa.application.commands import Command
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose

PRINCIPAL: Final = Principal(
    principal_id="prn_24abf5d2d0c25e1c82f6e72425e9ed37",
    kind=PrincipalKind.OPERATOR,
    authenticated=True,
)
FROZEN: Final = datetime(2026, 8, 15, 9, 30, tzinfo=UTC)

#: The names Phase B publishes. Written out so the sweep below is provably
#: about them and not merely about a set that happens to be large: a later
#: subtraction that quietly removed them would leave the population claim true
#: and this one false.
PHASE_B_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
    }
)


def _issue(_kind: object) -> str:
    return "corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _grants(capability: Capability) -> frozenset[tuple[Capability, Purpose | None]]:
    """A grant naming one permitted purpose, so purpose resolution never refuses.

    Without this a capability permitting more than one purpose and holding no
    canonical remote purpose would raise `UnsupportedError` on the *control*,
    and a control that cannot succeed proves nothing about the refusal beside it.
    """
    purpose = sorted(permitted_purposes(capability), key=lambda member: member.value)[0]
    return frozenset({(capability, purpose)})


def _compose(capability: Capability, arguments: dict[str, object]) -> dict[str, object]:
    return compose_remote_arguments(
        capability_name=capability.value,
        arguments=arguments,
        principal=PRINCIPAL,
        grants=_grants(capability),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )


def test_the_population_is_the_whole_capability_set() -> None:
    """No subtraction. The sweeps below are over everything this build publishes."""
    population = frozenset(Capability)
    assert population, "there are no capabilities, so nothing below proves anything"
    assert population >= PHASE_B_CAPABILITIES
    assert len(population) == len(list(Capability))


def test_the_field_sets_are_the_ones_the_contract_names() -> None:
    """Read the encoding rather than restate it, but check it still says §26's list."""
    assert {
        "capability",
        "contract_version",
        "principal_id",
        "purpose",
        "request_id",
        "requested_at",
        "scope",
    } <= SERVER_OWNED_REMOTE_FIELDS
    assert "idempotency_key" in REMOTE_OWNED_PAYLOAD_FIELDS


@pytest.mark.parametrize("field", sorted(SERVER_OWNED_REMOTE_FIELDS))
def test_no_capability_accepts_a_caller_supplied_envelope_field(field: str) -> None:
    """Every capability, against every envelope field the server owns.

    Parametrised by field and swept by capability inside, rather than the product
    as parametrisations: the product is several hundred cases whose failure
    message would say less than the capability name this assertion carries.
    """
    for capability in Capability:
        with pytest.raises(InvalidRequestError):
            _compose(capability, {field: "forged", "payload": {}})


def test_no_capability_accepts_a_caller_supplied_idempotency_key() -> None:
    """The payload half. A model inventing a replay key is inventing a request id."""
    for capability in Capability:
        for field in sorted(REMOTE_OWNED_PAYLOAD_FIELDS):
            with pytest.raises(InvalidRequestError):
                _compose(capability, {"payload": {field: "forged"}})


def test_the_same_request_without_the_field_is_composed() -> None:
    """The control for both sweeps above, on every capability they cover.

    A refusal is only evidence about the injected field if the request is
    otherwise acceptable. This is also what makes the sweeps non-vacuous: a
    change that made `compose_remote_arguments` refuse everything would pass both
    of them and fail here.
    """
    for capability in Capability:
        composed = _compose(capability, {"payload": {}})
        assert composed["principal_id"] == PRINCIPAL.principal_id
        assert composed["request_id"]
        permitted = {member.value for member in permitted_purposes(capability)}
        assert composed["purpose"] in permitted
        # `capability` is deliberately *not* among the stamped fields: the tool
        # name carries it, and it is in `SERVER_OWNED_REMOTE_FIELDS` so that a
        # caller who sends it anyway is refused rather than believed.
        assert "capability" not in composed


@pytest.mark.parametrize(
    "capability",
    [
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.REVIEW_DECIDE,
    ],
)
def test_replay_backed_remote_writes_receive_deterministic_server_request_ids(
    capability: Capability,
) -> None:
    assert is_server_replay_capability(capability)
    first = _compose(capability, {"payload": {"value": "same"}})
    retry = _compose(capability, {"payload": {"value": "same"}})
    changed = _compose(capability, {"payload": {"value": "changed"}})
    assert first["request_id"] == retry["request_id"]
    assert first["request_id"] != changed["request_id"]
    assert str(first["request_id"]).startswith("corr_")


@pytest.mark.parametrize(
    "capability",
    sorted(PHASE_B_CAPABILITIES, key=lambda member: member.value),
    ids=lambda member: member.value,
)
def test_phase_b_publishes_no_schema_naming_a_field_the_server_owns(
    capability: Capability,
) -> None:
    """The other direction: a published schema must not invite the refusal above.

    The Phase B names are covered here by capability rather than by prefix,
    because `relationship_memory.propose` does not carry the `entities.` prefix
    the Phase A sweep derives its population from and would otherwise be checked
    nowhere.
    """
    command = next(
        member for member in get_args(Command.__value__) if member.capability is capability
    )
    schema = remote_tool_schema(input_schema_for(command))
    assert not SERVER_OWNED_REMOTE_FIELDS & set(schema["properties"])
    payload = schema["properties"]["payload"]
    assert not REMOTE_OWNED_PAYLOAD_FIELDS & set(payload.get("properties", {}))
    assert "idempotency_key" not in payload.get("required", [])
