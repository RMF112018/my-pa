"""Synthetic wire checks for the exact off-by-default Apple machine routes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, cast

import pytest

from my_pa.adapters.http.app import APPLE_ADMIT_PATH, APPLE_POLL_PATH, create_http_app
from my_pa.application.apple_machine import (
    AppleBridgeIdentity,
    AppleMachineCredentialError,
)
from my_pa.application.native_sources import AdmissionDeniedError
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.principal import Principal, PrincipalKind
from wire import Wire, serve

CREDENTIAL = "AppleBridgeCredential abcred_0000000000000001:synthetic"
IDENTITY = AppleBridgeIdentity(
    "abcred_0000000000000001", "prn_0000000000000001", "nbrg_0000000000000001"
)


class Control:
    def poll(self, identity: AppleBridgeIdentity) -> Mapping[str, Any]:
        assert identity == IDENTITY
        return {"grant": "synthetic"}

    def admit(
        self, identity: AppleBridgeIdentity, document: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        assert identity == IDENTITY
        return {"receipt": document["authorityID"]}


class DeniedControl(Control):
    def admit(
        self, identity: AppleBridgeIdentity, document: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del identity, document
        raise AdmissionDeniedError("private durable denial detail")


@pytest.fixture
def service() -> ApplicationService:
    return cast(ApplicationService, object())


def operator() -> Principal:
    return Principal("prn_0000000000000009", PrincipalKind.OPERATOR, True)


def auth(header: str | None) -> AppleBridgeIdentity:
    if header != CREDENTIAL:
        raise AppleMachineCredentialError()
    return IDENTITY


def post(wire: Wire, path: str, document: Mapping[str, Any], credential: str) -> Any:  # noqa: ANN401
    return wire.send("unused", document, path=path, extra_headers={"authorization": credential})


@pytest.fixture
def disabled(service: ApplicationService) -> Iterator[Wire]:
    with serve(create_http_app(service, principal=operator())) as wire:
        yield wire


@pytest.fixture
def enabled(service: ApplicationService) -> Iterator[Wire]:
    app = create_http_app(
        service,
        principal=operator(),
        apple_authenticate=auth,
        apple_control=Control(),
    )
    with serve(app) as wire:
        yield wire


def test_apple_routes_are_mounted_but_off_by_default(disabled: Wire) -> None:
    response = post(disabled, APPLE_POLL_PATH, {}, CREDENTIAL)
    assert response.status == 501


def test_only_dedicated_credential_reaches_exact_routes(enabled: Wire) -> None:
    assert post(enabled, APPLE_POLL_PATH, {}, CREDENTIAL).status == 200
    refused = post(enabled, APPLE_POLL_PATH, {}, "Bearer synthetic")
    assert refused.status == 401
    assert refused.headers["www-authenticate"] == "AppleBridgeCredential"
    admitted = post(
        enabled,
        APPLE_ADMIT_PATH,
        {"authorityID": "nauth_0000000000000001", "envelope": {}},
        CREDENTIAL,
    )
    assert admitted.status == 200


def test_apple_machine_route_accepts_the_host_envelope_specific_body_bound(
    enabled: Wire,
) -> None:
    response = post(enabled, APPLE_POLL_PATH, {"padding": "x" * 800_000}, CREDENTIAL)
    assert response.status == 200


@pytest.mark.parametrize("field", ["principal_id", "principalID", "bridgeID"])
def test_caller_cannot_supply_identity(enabled: Wire, field: str) -> None:
    response = post(enabled, APPLE_ADMIT_PATH, {field: "forged"}, CREDENTIAL)
    assert response.status == 400


def test_durable_admission_denial_uses_the_fixed_safe_wire_response(
    service: ApplicationService,
) -> None:
    app = create_http_app(
        service,
        principal=operator(),
        apple_authenticate=auth,
        apple_control=DeniedControl(),
    )
    with serve(app) as wire:
        response = post(
            wire,
            APPLE_ADMIT_PATH,
            {"authorityID": "nauth_0000000000000001", "envelope": {}},
            CREDENTIAL,
        )
    assert response.status == 403
    assert response.document()["code"] == "denied"
    assert "private durable denial detail" not in response.body
