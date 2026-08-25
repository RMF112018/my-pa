"""Proposal provenance is selected by immutable authenticated registration."""

from __future__ import annotations

import dataclasses

import pytest

from my_pa.application.commands import CreateEntityProposal, ProposeRelationshipMemory
from my_pa.application.producer_origin import (
    ProducerOrigin,
    ProducerOriginError,
    ProducerOriginRegistry,
)
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.relationship.proposal_payload import FORBIDDEN_PAYLOAD_FIELDS

PROVENANCE_FIELDS = frozenset({"method", "method_version", "model_id", "model_version"})
PRODUCER_ID = "prn_24abf5d2d0c25e1c82f6e72425e9ed37"


@pytest.mark.parametrize("command", [CreateEntityProposal, ProposeRelationshipMemory])
def test_no_producer_command_carries_a_method_or_model(command: type) -> None:
    assert not {field.name for field in dataclasses.fields(command)} & PROVENANCE_FIELDS


def test_nested_entity_payload_refuses_provenance_names() -> None:
    assert PROVENANCE_FIELDS <= FORBIDDEN_PAYLOAD_FIELDS


def test_registry_resolves_only_the_exact_authenticated_principal() -> None:
    origin = ProducerOrigin(
        principal_id=PRODUCER_ID,
        principal_kind=PrincipalKind.LOCAL_MODEL_GATEWAY,
        method="local_model",
        method_version="relationship-producer.3",
        model_id="local.relationship",
        model_version="sha256:0123456789abcdef",
    )
    registry = ProducerOriginRegistry({PRODUCER_ID: origin})
    assert registry.resolve(
        Principal(PRODUCER_ID, PrincipalKind.LOCAL_MODEL_GATEWAY, authenticated=True)
    ) is origin
    with pytest.raises(ProducerOriginError):
        registry.resolve(Principal(PRODUCER_ID, PrincipalKind.OPERATOR, authenticated=True))
    with pytest.raises(ProducerOriginError):
        registry.resolve(
            Principal(PRODUCER_ID, PrincipalKind.LOCAL_MODEL_GATEWAY, authenticated=False)
        )


def test_local_model_identity_is_exact_and_non_model_origins_cannot_name_one() -> None:
    with pytest.raises(ValueError):
        ProducerOrigin(
            principal_id=PRODUCER_ID,
            principal_kind=PrincipalKind.LOCAL_MODEL_GATEWAY,
            method="local_model",
            method_version="producer.1",
        )
    with pytest.raises(ValueError):
        ProducerOrigin(
            principal_id=PRODUCER_ID,
            principal_kind=PrincipalKind.WORKER,
            method="rule",
            method_version="producer.1",
            model_id="forged",
            model_version="forged",
        )
