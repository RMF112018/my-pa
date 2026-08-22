"""The remote capture ingress, over a real socket, with the store faked.

WP-10. What this module proves is everything about the ingress that does not
need a database: the kill switch, the credential plane, the address, and the
refusals. The durable half — that a remote submission lands in the same
transaction, replays idempotently, and stores what a local one stores — is
`tests/capture/test_remote_capture_is_one_durable_transaction.py`'s, against real
PostgreSQL, because a fake unit of work would agree with whatever this module
believed.

Every request goes over a loopback socket through uvicorn, for the reason
`tests/wire.py` gives: the claims here are about what a caller receives, and an
in-process ASGI call would skip the server that frames it.

**The kill switch is asserted at the handler, not at the routing table.** The
route is mounted whether or not the ingress is composed, so the disabled case is
a real `POST` that a real handler answers — and it is answered `501` *before* the
credential is read, which the tests below drive by sending a perfectly good
credential and getting the refusal anyway.

**The two credential planes are shown to be disjoint from outside the process.**
A client credential presented to `/v1/{capability}` in the authenticated mode is
refused; a bearer token presented to the ingress is refused; the challenge
headers name different schemes. None of that is a statement about the code — it
is four requests and four answers.

Everything is synthetic: `client_test_0000…` identifiers, `synthetic-…` secrets,
an in-memory world, and a socket the kernel chose.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

import pytest
from tests.conftest import WHEN, FakeProviders, World, build_service, operator
from tests.wire import Reply, Wire, serve

from my_pa.adapters.http import PATH_TEMPLATE, REMOTE_CAPTURE_CAPABILITY, REMOTE_CAPTURE_PATH
from my_pa.adapters.http.app import create_http_app
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.identity.user_account import TokenClaimsError

#: An obviously synthetic credential. It names no real client and no real secret;
#: the authenticator below is a stub, so nothing here is a value that could work
#: anywhere.
CLIENT_ID: Final = "cclt_clienttest00000000000000000000"
CLIENT_SECRET: Final = "synthetic-a-value-that-authenticates-nothing"  # noqa: S105
CREDENTIAL: Final = f"ClientCredential {CLIENT_ID}:{CLIENT_SECRET}"

#: A bearer token, presented at the ingress to prove the schemes do not cross.
#: Not a token: an obviously synthetic string.
BEARER: Final = "Bearer synthetic-not-a-token"

WHEN_WIRE: Final = "2026-08-03T12:00:00Z"
IOS_SHORTCUT_FIXTURE: Final = (
    Path(__file__).resolve().parents[2] / "fixtures/remote-capture/ios-shortcut-request.json"
)


@pytest.fixture
def service(world: World) -> ApplicationService:
    return build_service(world, FakeProviders({}))


@pytest.fixture
def remote_principal() -> Principal:
    """The Principal a registered client resolves to. One, always the same."""
    return operator()


def stub_client(principal: Principal) -> Any:  # noqa: ANN401 - the composed callable's own shape
    """A composition root's remote authenticator, reduced to its contract.

    It accepts exactly one credential string and refuses everything else with
    `TokenClaimsError`, which is the one refusal the real one raises for all five
    of its failure modes. The real resolution — the database read, the digest
    comparison, the revocation check and the binding check — is proved against
    real PostgreSQL elsewhere; what this stands in for here is *that* the
    transport consults the composition root and maps its refusal onto a status.
    """

    def authenticate(credential: str | None) -> Principal:
        if credential != CREDENTIAL:
            raise TokenClaimsError("a registered capture client is required; access is denied")
        return principal

    return authenticate


def submission(**payload: object) -> dict[str, Any]:
    """A canonical request document with no `principal_id` in it.

    The absence is the contract on this plane: the caller may not state an
    identity and the transport supplies the one it authenticated. Everything else
    is the same envelope every other transport sends.
    """
    return {
        "request_id": "req-remote-1",
        "purpose": Purpose.CAPTURE_AUTHORING.value,
        "requested_at": WHEN_WIRE,
        "payload": {"text": "a synthetic note", "idempotency_key": "remote-1", **payload},
    }


def test_ios_shortcut_fixture_is_the_same_bounded_principal_free_contract() -> None:
    document = json.loads(IOS_SHORTCUT_FIXTURE.read_text())
    assert set(document) == {"request_id", "purpose", "requested_at", "payload"}
    assert set(document["payload"]) == {"text", "idempotency_key"}
    assert document["purpose"] == Purpose.CAPTURE_AUTHORING.value
    assert "principal_id" not in IOS_SHORTCUT_FIXTURE.read_text()
    assert "credential" not in IOS_SHORTCUT_FIXTURE.read_text().lower()


@pytest.fixture
def enabled(service: ApplicationService, remote_principal: Principal) -> Iterator[Wire]:
    """The gateway with the ingress composed: the operator turned it on."""
    application = create_http_app(
        service, principal=operator(), remote_client=stub_client(remote_principal)
    )
    with serve(application) as wire:
        yield wire


@pytest.fixture
def disabled(service: ApplicationService) -> Iterator[Wire]:
    """The gateway as every unconfigured process composes it: no ingress."""
    with serve(create_http_app(service, principal=operator())) as wire:
        yield wire


def post(wire: Wire, document: Mapping[str, Any] | None, *, credential: str | None = None) -> Reply:
    headers = {} if credential is None else {"authorization": credential}
    return wire.send(
        REMOTE_CAPTURE_CAPABILITY,
        dict(document or {}),
        path=REMOTE_CAPTURE_PATH,
        extra_headers=headers,
    )


# ---- the kill switch ----------------------------------------------------------


def test_the_ingress_refuses_when_it_was_never_composed(disabled: Wire) -> None:
    """Control 5, at the handler: a good credential still gets nothing.

    The credential below is the one the enabled fixture accepts, so the refusal
    cannot be about authentication — and the switch is read before the credential
    is, which is why the `501` arrives rather than a `401`. A route that vanished
    when the switch was off would answer `404` here and would prove only that
    Starlette has no such path.
    """
    refused = post(disabled, submission(), credential=CREDENTIAL)
    assert refused.status == 501, refused.body
    assert refused.document()["code"] == ErrorCode.UNSUPPORTED.value
    assert "www-authenticate" not in refused.headers, (
        "a disabled ingress challenged for a credential, which invites the caller "
        "to send one; the switch is read before the credential is"
    )


def test_the_disabled_ingress_is_a_mounted_route_rather_than_an_absent_one(
    disabled: Wire,
) -> None:
    """The distinction the test above rests on, asserted rather than assumed.

    An unroutable path answers `404`; the ingress answers `501`. If those were
    ever the same answer, "disabled means the handler refused" and "disabled
    means the route is not there" would be indistinguishable from outside — and
    only the first is a claim about what happens when the switch is off.
    """
    unroutable = disabled.send(
        REMOTE_CAPTURE_CAPABILITY, submission(), path="/remote/v1/capture.revise"
    )
    assert unroutable.status == 404
    assert post(disabled, submission(), credential=CREDENTIAL).status == 501


def test_a_disabled_ingress_reaches_the_application_not_at_all(
    service: ApplicationService, world: World, disabled: Wire
) -> None:
    """Disabled is not "served and then discarded": nothing is admitted."""
    assert post(disabled, submission(), credential=CREDENTIAL).status == 501
    assert world.capture_admissions == [], (
        "a refused ingress request reached the capture store; the switch has to "
        "stop the request rather than its answer"
    )


# ---- the credential -----------------------------------------------------------


def test_an_enabled_ingress_admits_a_registered_client(enabled: Wire, world: World) -> None:
    """The positive control. Without it every refusal below is a broken transport."""
    accepted = post(enabled, submission(), credential=CREDENTIAL)
    assert accepted.status == 200, accepted.body
    assert accepted.document()["result"]["created"] is True
    assert len(world.capture_admissions) == 1


@pytest.mark.parametrize(
    ("credential", "why"),
    [
        (None, "no credential at all"),
        (BEARER, "a bearer token, which is the other plane's scheme"),
        (f"ClientCredential {CLIENT_ID}:wrong-secret", "the right client, the wrong secret"),
        ("ClientCredential nonsense", "a credential with no separator"),
        (f"Basic {CLIENT_ID}:{CLIENT_SECRET}", "the right value under the wrong scheme"),
        (
            "ClientCredential prn_someoneelsesprincipalidentifier:s",
            "an identifier of the wrong kind, which used to escape as a 500",
        ),
    ],
    ids=["absent", "bearer", "wrong-secret", "malformed", "basic", "wrong-identifier-kind"],
)
def test_every_bad_credential_gets_the_same_refusal(
    enabled: Wire, world: World, credential: str | None, why: str
) -> None:
    """Five ways to fail, one answer, and no admission behind any of them.

    Byte-identical bodies except for the correlation identifier, which is issued
    per request — so a caller cannot subtract two refusals and learn which of the
    five it hit. The `www-authenticate` header names this plane's scheme and no
    realm, no error code, and no scope.
    """
    refused = post(enabled, submission(), credential=credential)
    assert refused.status == 401, why
    assert refused.headers["www-authenticate"] == "ClientCredential", (
        "the challenge named a realm, an error, or another scheme; each of those "
        "describes the deployment to whoever asks"
    )
    assert refused.document()["code"] == ErrorCode.DENIED.value
    assert refused.document()["safe_details"] == []
    assert world.capture_admissions == [], why


def test_the_five_refusals_are_one_answer(enabled: Wire) -> None:
    """The refusals are indistinguishable, which the test above cannot say alone.

    Asserting each one's shape separately would pass on five *different* bodies
    that each had the right keys. This collects all five and requires the bodies
    to be equal once the per-request correlation identifier is removed — so no
    caller can subtract two answers and learn whether the client exists, whether
    the secret was right, or whether it was revoked.
    """
    bodies = []
    for credential in (
        None,
        BEARER,
        f"ClientCredential {CLIENT_ID}:wrong-secret",
        "ClientCredential nonsense",
        f"Basic {CLIENT_ID}:{CLIENT_SECRET}",
    ):
        refused = post(enabled, submission(), credential=credential)
        document = refused.document()
        correlation = document.pop("correlation_id")
        assert correlation.startswith("corr_")
        bodies.append((refused.status, refused.headers["www-authenticate"], document))
    assert len(bodies) == 5
    assert bodies.count(bodies[0]) == 5, f"the refusals differ: {bodies}"


def test_a_client_credential_cannot_invoke_a_capability_on_the_other_plane(
    service: ApplicationService, remote_principal: Principal
) -> None:
    """The disjointness, from the outside, in the direction that matters most.

    A gateway in the authenticated mode reads `Authorization: Bearer …` on
    `/v1/{capability}`. A client credential presented there is refused for its
    scheme — so holding a device credential buys nothing on the capability plane,
    including the operator-only capabilities a device must never reach.
    """

    def bearer_only(credential: str | None, document: Mapping[str, Any]) -> Principal:
        """The Entra authenticator's contract: bearer or nothing."""
        if credential is None or not credential.lower().startswith("bearer "):
            raise TokenClaimsError("a bearer token is required; access is denied")
        return operator()

    application = create_http_app(
        service, authenticate=bearer_only, remote_client=stub_client(remote_principal)
    )
    with serve(application) as wire:
        refused = wire.send(
            REMOTE_CAPTURE_CAPABILITY,
            {**submission(), "principal_id": remote_principal.principal_id},
            path=PATH_TEMPLATE.format(capability=REMOTE_CAPTURE_CAPABILITY),
            extra_headers={"authorization": CREDENTIAL},
        )
        assert refused.status == 401
        assert refused.headers["www-authenticate"] == "Bearer", (
            "the capability plane challenged for a client credential; the two "
            "planes have to name different schemes or they are one plane"
        )


# ---- the address --------------------------------------------------------------


def test_the_ingress_address_carries_no_placeholder() -> None:
    """A remote client addresses one capability and cannot name another.

    `PATH_TEMPLATE` has a `{capability}` segment because a local caller reaches
    sixty-five capabilities. The ingress has none, so there is no segment a remote
    client could put a different name in — and nothing to enforce, because there
    is nothing to enforce it against.
    """
    assert "{" not in REMOTE_CAPTURE_PATH
    assert REMOTE_CAPTURE_PATH.endswith(REMOTE_CAPTURE_CAPABILITY)
    assert "{capability}" in PATH_TEMPLATE


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "PATCH"], ids=lambda v: str(v))
def test_the_ingress_answers_one_method(enabled: Wire, method: str) -> None:
    """A capture is a `POST`. Everything else is HTTP's own `405`."""
    answer = enabled.send(
        REMOTE_CAPTURE_CAPABILITY, submission(), path=REMOTE_CAPTURE_PATH, method=method
    )
    assert answer.status == 405


def test_a_query_string_is_refused_rather_than_ignored(enabled: Wire, world: World) -> None:
    """`QC-AC-041`'s URL sink, closed at the transport rather than inferred.

    The body here is complete and would succeed on its own — the control below
    proves it — so the refusal is about the query string and nothing else. That
    is the difference between refusing a URL parameter and merely not reading
    one: a caller that sent both would otherwise be told the URL half was fine.
    """
    refused = enabled.send(
        REMOTE_CAPTURE_CAPABILITY,
        submission(),
        path=f"{REMOTE_CAPTURE_PATH}?text=a-synthetic-note",
        extra_headers={"authorization": CREDENTIAL},
    )
    assert refused.status == 400
    assert refused.document()["code"] == ErrorCode.INVALID_REQUEST.value
    assert world.capture_admissions == []

    assert post(enabled, submission(), credential=CREDENTIAL).status == 200


# ---- the identity -------------------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        {**submission(), "principal_id": "prn_someoneelsesprincipalidentifier"},
        {
            **submission(),
            "payload": {
                "text": "a synthetic note",
                "idempotency_key": "remote-1",
                "principal_id": "prn_someoneelsesprincipalidentifier",
            },
        },
    ],
    ids=["envelope", "payload"],
)
def test_a_caller_stated_identity_is_refused_on_this_plane(
    enabled: Wire, world: World, document: dict[str, Any]
) -> None:
    """Narrower than every other transport, deliberately.

    Elsewhere `metadata.principal_id` is required by the contract, accepted, and
    read by nothing. Here the caller may not state it at all, in the envelope or
    in the payload, and the transport supplies the identifier the credential
    resolved to. A remote caller therefore has no field through which to name a
    partition, which is a stronger property than one that is ignored.
    """
    refused = post(enabled, document, credential=CREDENTIAL)
    assert refused.status == 400
    assert refused.document()["code"] == ErrorCode.INVALID_REQUEST.value
    assert world.capture_admissions == []


def test_the_admitted_request_runs_as_the_credentials_principal(
    enabled: Wire, world: World, remote_principal: Principal
) -> None:
    """Whose capture it is comes from the credential, and from nothing else.

    The document names no Principal at all, and the admission still lands in the
    resolved one's partition. There is no arrangement of this request that could
    have put it anywhere else, because there is no field to put it in.
    """
    assert post(enabled, submission(), credential=CREDENTIAL).status == 200
    admitted = world.capture_admissions[-1]
    assert admitted.principal_id == remote_principal.principal_id


def test_the_admission_records_the_remote_transport(enabled: Wire, world: World) -> None:
    """Provenance, and it is the transport's rather than the caller's.

    The document is identical to one a local caller would send. What makes the
    stored submission say `remote_client` is which route it arrived on, which the
    caller does not choose and cannot state.
    """
    assert post(enabled, submission(), credential=CREDENTIAL).status == 200
    assert world.capture_admissions[-1].transport.value == "remote_client"


def test_a_local_submission_of_the_same_document_records_the_local_transport(
    service: ApplicationService, world: World, remote_principal: Principal
) -> None:
    """The control that makes the assertion above a measurement.

    The same document, the same capability, the same application — over
    `/v1/capture.create` instead. It records `local`, so "the ingress records
    `remote_client`" is a difference this test produced rather than a constant
    the fake happens to return.
    """
    local = operator()
    application = create_http_app(service, principal=local)
    with serve(application) as wire:
        accepted = wire.send(
            REMOTE_CAPTURE_CAPABILITY,
            {**submission(), "principal_id": local.principal_id},
        )
    assert accepted.status == 200, accepted.body
    assert world.capture_admissions[-1].transport.value == "local"


# ---- the bounds ---------------------------------------------------------------


def test_the_ingress_refuses_a_body_it_cannot_bound(enabled: Wire, world: World) -> None:
    """The same transport bounds the capability plane enforces, on the same code.

    Chunked framing has no declared length, so the ingress refuses it exactly as
    `/v1/{capability}` does. Asserted here rather than assumed because the ingress
    is the one address a device on the far side of a proxy reaches, and a bound
    that held on only one of two routes would be no bound at all.
    """
    refused = enabled.send(
        REMOTE_CAPTURE_CAPABILITY,
        submission(),
        path=REMOTE_CAPTURE_PATH,
        omit_content_length=True,
        extra_headers={"authorization": CREDENTIAL},
    )
    assert refused.status == 400
    assert world.capture_admissions == []


def test_the_ingress_refuses_a_body_that_is_not_json(enabled: Wire, world: World) -> None:
    refused = enabled.send(
        REMOTE_CAPTURE_CAPABILITY,
        None,
        raw="a synthetic note",
        path=REMOTE_CAPTURE_PATH,
        content_type="text/plain",
        extra_headers={"authorization": CREDENTIAL},
    )
    assert refused.status == 400
    assert world.capture_admissions == []


def test_the_ingress_composes_with_either_authentication_mode(
    service: ApplicationService, remote_principal: Principal
) -> None:
    """It is a second plane, not a third mode.

    Composing the ingress alongside the fixed local principal and alongside a
    per-request authenticator both succeed, which is what "orthogonal" means
    here. Composing the two *modes* together still raises, unchanged.
    """

    def bearer_only(credential: str | None, document: Mapping[str, Any]) -> Principal:
        raise TokenClaimsError("a bearer token is required; access is denied")

    create_http_app(service, principal=operator(), remote_client=stub_client(remote_principal))
    create_http_app(service, authenticate=bearer_only, remote_client=stub_client(remote_principal))
    with pytest.raises(ValueError, match="exactly one"):
        create_http_app(
            service,
            principal=operator(),
            authenticate=bearer_only,
            remote_client=stub_client(remote_principal),
        )
    assert WHEN is not None


# ---- the terminal catches, which shipped unarmed ------------------------------


@pytest.mark.parametrize("stage", ["build", "invoke"])
def test_a_fault_on_this_route_is_answered_in_the_envelope(
    enabled: Wire,
    remote_principal: Principal,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    """The two `except Exception` clauses on `submit`, which had no test at all.

    A previous commit added the terminal catch to the `invoke` route *and* a
    test arming it, then added the same catch here and no test. The eleventh
    review measured the result: deleting either clause left the whole fast tier
    and the database tier green. Two independent lenses reported it, which is
    what a rule shipped without its guard looks like.

    Both stages are exercised because they are separate `try` blocks and each
    can be removed on its own. `build` covers the body read, the caller-identity
    strip and `normalize`; `invoke` covers the application call.
    """
    if stage == "build":

        def explode(capability: str, arguments: object) -> object:
            raise AttributeError("'int' object has no attribute 'strip'")

        monkeypatch.setattr("my_pa.adapters.http.app.normalize", explode)
    else:

        def erupt(*args: object, **kwargs: object) -> object:
            raise RuntimeError("a fault below the transport")

        monkeypatch.setattr(ApplicationService, "invoke", erupt)

    reply = post(enabled, submission(), credential=CREDENTIAL)
    assert reply.status == 500, reply.body
    body = reply.document()
    assert body["code"] == ErrorCode.INTERNAL_ERROR.value
    assert body["correlation_id"]
    assert "strip" not in reply.rendered()
    assert "fault below" not in reply.rendered()
