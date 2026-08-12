"""The web BFF and the Python gateway agree on what a request is, by construction.

`web/src/contracts/gateway.json` is the only description of a `POST
/v1/{capability}` request either tier holds. `web/src/lib/api/gateway.ts` imports
it and builds every document from it; this module loads the same bytes and checks
them against the things that would actually reject a request — `Capability`,
`_PERMITTED_PURPOSES`, `RequestMetadata`, `_BUILDERS`, and each command's own
dataclass fields — and then feeds every declared `probe` through `normalize()`.

**Derived rather than copied, and the difference is the whole point.** A test
holding its own hand-written sample of what the web sends would go on passing
after the web changed, because it would be checking this file's memory of the
frontend rather than the frontend. There is one copy of the contract, both tiers
read it, and a change on either side that the other has not followed fails here.

The `probe` payloads are synthetic: no tenant, no credential, no path, no person.
They exist to be *accepted*, so they carry the minimum each command requires.

Nothing here opens a connection, reaches a source, or touches a database.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.adapters.http.app import PATH_TEMPLATE
from my_pa.adapters.normalization import _BUILDERS, PAYLOAD_KEY, normalize
from my_pa.contracts.v1.base import CONTRACT_VERSION
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.capture.review import Disposition
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT_PATH: Final = ROOT / "web" / "src" / "contracts" / "gateway.json"
WEB_SOURCE: Final = ROOT / "web" / "src"

#: A synthetic correlation identifier of the shape the BFF derives. Its value is
#: irrelevant to every assertion here: `metadata.principal_id` is correlation
#: input the application does not read, and
#: `tests/architecture/test_principal_is_never_caller_supplied.py` is what keeps
#: that a measurement rather than a habit.
PROBE_PRINCIPAL: Final = "prn_" + "a" * 32


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    """The shared contract, parsed. A missing or malformed file is a failure."""
    assert CONTRACT_PATH.is_file(), f"the shared BFF contract is missing at {CONTRACT_PATH}"
    parsed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


@pytest.fixture(scope="module")
def declared(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The capability entries, which must be non-empty for anything below to mean something."""
    capabilities = contract["capabilities"]
    assert isinstance(capabilities, dict) and capabilities, (
        "the shared contract declares no capability, so every parametrised check below "
        "would pass by describing nothing"
    )
    return capabilities


def test_the_transport_addressing_matches(contract: dict[str, Any]) -> None:
    """The path, the contract version, and the payload key are the gateway's own."""
    assert contract["pathTemplate"] == PATH_TEMPLATE
    assert contract["contractVersion"] == CONTRACT_VERSION
    assert contract["payloadKey"] == PAYLOAD_KEY


def test_the_envelope_fields_are_exactly_the_metadata_model_minus_what_is_not_sent(
    contract: dict[str, Any],
) -> None:
    """What the BFF sends, plus what it must not, is the whole of `RequestMetadata`.

    `capability` is routed on rather than sent: `normalize` supplies it from the
    path, and a document naming it too would hand `RequestMetadata` the argument
    twice and be refused. `scope` is omitted because the declared scope is
    correlation input authorization does not read, and this tier has no grant to
    declare. Everything else is required and is sent.
    """
    sent = set(contract["envelopeFields"])
    routed = contract["routedField"]
    model = set(RequestMetadata.model_fields)
    assert routed in model
    assert sent <= model, f"the BFF sends fields the envelope has no place for: {sent - model}"
    assert sent | {routed, "scope"} == model, (
        "the BFF's envelope and RequestMetadata have diverged: "
        f"unsent required fields {model - sent - {routed, 'scope'}}"
    )


def test_every_declared_capability_is_one_this_build_serves(
    declared: dict[str, dict[str, Any]],
) -> None:
    """A name the BFF can address is a `Capability` with a builder behind it."""
    for name in declared:
        capability = Capability(name)  # raises for a name that is not one
        assert capability in _BUILDERS, f"{name} has no normalisation builder"


def test_every_declared_purpose_may_invoke_its_capability(
    declared: dict[str, dict[str, Any]],
) -> None:
    """The purpose the BFF states is one the domain permits for that capability.

    A purpose the domain does not permit is denied by policy at request time,
    which would make every one of these routes fail in the field while every web
    test stayed green.
    """
    for name, entry in declared.items():
        capability = Capability(name)
        purpose = Purpose(entry["purpose"])
        assert purpose in permitted_purposes(capability), (
            f"{name} declares purpose {purpose}, which the domain does not permit for it"
        )


def test_declared_payload_fields_are_exactly_the_commands_own(
    declared: dict[str, dict[str, Any]],
) -> None:
    """The BFF knows each command's field set exactly — no extras, none missing.

    Both directions matter. A field the command does not have is a `TypeError` in
    the builder and an `invalid_request` to the caller; a field the command has
    that the contract omits is a capability the BFF silently cannot use fully.
    """
    for name, entry in declared.items():
        command = _BUILDERS[Capability(name)](entry["probe"])
        actual = {field.name for field in dataclasses.fields(command)}
        stated = set(entry["payloadFields"])
        assert stated == actual, (
            f"{name}: contract states {sorted(stated)}, command has {sorted(actual)}"
        )


def test_every_probe_document_is_accepted_by_normalize(
    contract: dict[str, Any], declared: dict[str, dict[str, Any]]
) -> None:
    """The document the BFF builds is one `normalize` turns into a request pair.

    This is the assertion the rest of the module exists to make meaningful: the
    envelope keys come from `envelopeFields`, the payload from the entry's own
    `probe`, and the pair that comes back has to name the capability that was
    routed on.
    """
    for name, entry in declared.items():
        document = {
            "contract_version": contract["contractVersion"],
            "request_id": f"bff-probe-{name}",
            "purpose": entry["purpose"],
            "principal_id": PROBE_PRINCIPAL,
            "requested_at": "2026-08-09T12:00:00Z",
            contract["payloadKey"]: entry["probe"],
        }
        assert set(document) - {contract["payloadKey"]} == set(contract["envelopeFields"]), (
            "this test must build its document out of the contract's own envelope fields, "
            "or it is checking a shape the BFF does not send"
        )
        metadata, command = normalize(name, document)
        assert metadata.capability is Capability(name)
        assert command.capability is Capability(name)
        assert metadata.purpose is Purpose(entry["purpose"])


def test_the_disposition_translation_lands_on_real_domain_members(
    contract: dict[str, Any],
) -> None:
    """Every workbench verb maps to a `Disposition` the domain actually has.

    Two of the five are spelled differently on the two sides, so this map is not
    decoration: an unmapped or misspelled value would reach the gateway as an
    `invalid_request` that only the field would see.
    """
    dispositions = contract["dispositions"]
    assert isinstance(dispositions, dict) and dispositions
    for web_value, domain_value in dispositions.items():
        assert isinstance(web_value, str) and web_value
        assert Disposition(domain_value)
    assert set(dispositions.values()) <= {member.value for member in Disposition}


#: A `callGateway(<expr>, "<capability>"` call in the web tree. Matched across
#: the argument break because the routes wrap the call over several lines.
_CALL_SITE: Final = re.compile(r"callGateway<?[^(]*\(\s*[^,]+,\s*\"([a-z_.]+)\"", re.MULTILINE)


def test_no_web_module_addresses_a_capability_the_contract_does_not_declare(
    declared: dict[str, dict[str, Any]],
) -> None:
    """Every capability a route actually calls is one this contract covers.

    The TypeScript type already narrows `callGateway`'s second argument to the
    contract's keys, so this is the second lock rather than the first — but it is
    the one that still holds if a route reaches for `as GatewayCapability`, and it
    is what makes the parity above cover the *used* set rather than an arbitrary
    one.
    """
    assert WEB_SOURCE.is_dir(), "the web source tree is missing"
    called: set[str] = set()
    for path in sorted(WEB_SOURCE.rglob("*.ts")):
        called.update(_CALL_SITE.findall(path.read_text(encoding="utf-8")))
    assert called, "no callGateway site was found, so this rule is describing nothing"
    undeclared = called - set(declared)
    assert not undeclared, (
        f"web modules call capabilities the shared contract does not declare: {undeclared}"
    )
