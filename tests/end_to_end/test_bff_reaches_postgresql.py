"""The BFF's own document, over a real socket, into a real PostgreSQL row.

This is the chain the operating brief asks for, walked rather than described:
the request document `web/src/lib/api/gateway.ts` builds -> `POST
/v1/{capability}` on a uvicorn server this test starts -> `normalize` ->
`ApplicationService.invoke` -> the authorization path -> `SqlAlchemyUnitOfWork`
-> a row in PostgreSQL that this test then reads back with SQL of its own.

Two things are proved, and they are different claims:

1. **A capability the BFF wires reaches the database.** `capture.create` is sent
   exactly as the BFF sends it — the envelope keys come from
   `web/src/contracts/gateway.json`, not from this file's opinion of them — and
   the `receipt_id` in the response is then found in `knowledge.capture_receipts`
   and joined back to `knowledge.captures`. Reading the row back is the point: a
   `200` proves the process answered, and only the row proves it persisted.

2. **A foreign `principal_id` in the envelope is ignored, not honoured.** The
   same request is sent twice, differing only in `metadata.principal_id`: once
   with the correlation identifier the BFF would derive from the session, once
   with a `prn_` naming a principal this process is not. Both are served as the
   *process* principal, the stored `owner_principal_id` is that principal in both
   cases, the foreign identifier appears nowhere in the database, and a
   `capture.list` sent under the foreign envelope returns the process principal's
   captures rather than an empty page. That is the WP-05 property (D-13) held at
   the transport rather than restated: `metadata.principal_id` is correlation
   input and is read by nothing.

**`local_operator` mode is the mode under test, and that is deliberate.** It is
what a BFF deployment can actually run today: `POST /api/session` on the web tier
implements no real Entra sign-in, so no session there holds a bearer token to
forward, and the BFF refuses `entra` mode rather than sending an unauthenticated
request or minting one. The isolation claim proved here is therefore "a stated
identity changes nothing", which is the claim that holds in both modes — not "two
principals are partitioned", which this mode cannot express and which this test
does not assert.

The database is a disposable one this module creates and drops. Every value is
synthetic: no tenant, no credential, no path, no person, no live source.
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from tests.wire import Wire, serve

from my_pa.adapters.http import create_http_app
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = [pytest.mark.database, pytest.mark.e2e]

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT_PATH: Final = ROOT / "web" / "src" / "contracts" / "gateway.json"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE: Final = "my_pa_bff_chain_test"

#: A correlation identifier of the shape `correlationPrincipalId` derives in
#: `web/src/lib/api/gateway.ts`: `prn_` and 32 hexadecimal characters. Synthetic.
SESSION_CORRELATION: Final = "prn_" + "1a2b3c4d" * 4

#: A `prn_` naming somebody this process is not. The whole test is that sending
#: it changes nothing at all.
FOREIGN_PRINCIPAL: Final = "prn_" + "f0f0f0f0" * 4


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    """The shared BFF request contract, so the documents below are the BFF's."""
    assert CONTRACT_PATH.is_file(), f"the shared BFF contract is missing at {CONTRACT_PATH}"
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture(scope="module")
def runtime(disposable_database: str) -> Iterator[GatewayRuntime]:
    """The real composition root, over the disposable database."""
    built = build_gateway_runtime(Settings(database_url=disposable_database))
    try:
        yield built
    finally:
        built.close()


def bff_document(
    contract: dict[str, Any], capability: str, payload: dict[str, Any], *, principal_id: str
) -> dict[str, Any]:
    """One request document, assembled exactly as the BFF assembles one.

    The envelope keys are read off the shared contract rather than typed here, so
    a field the BFF starts or stops sending changes this test too. `capability`
    is deliberately absent: it is routed on, and a document naming it is refused.
    """
    entry = contract["capabilities"][capability]
    document = {
        "contract_version": contract["contractVersion"],
        "request_id": f"bff-{capability}-{principal_id[-8:]}",
        "purpose": entry["purpose"],
        "principal_id": principal_id,
        "requested_at": "2026-08-09T12:00:00Z",
        contract["payloadKey"]: payload,
    }
    assert set(document) - {contract["payloadKey"]} == set(contract["envelopeFields"])
    return document


@pytest.fixture(scope="module")
def wire(runtime: GatewayRuntime) -> Iterator[Wire]:
    """The gateway on a loopback socket, composed as `apps/gateway.py` composes it."""
    assert runtime.principal is not None, "this module exercises local_operator mode"
    with serve(create_http_app(runtime.service, principal=runtime.principal)) as client:
        yield client


def test_a_capture_sent_as_the_bff_sends_it_lands_in_postgresql(
    wire: Wire, runtime: GatewayRuntime, contract: dict[str, Any]
) -> None:
    """`capture.create` over HTTP writes the row, and the row is read back with SQL."""
    reply = wire.send(
        "capture.create",
        bff_document(
            contract,
            "capture.create",
            {"text": "a synthetic note from the BFF chain test", "idempotency_key": "bff-chain-1"},
            principal_id=SESSION_CORRELATION,
        ),
    )
    assert reply.status == 200, reply.rendered()
    envelope = reply.document()
    assert envelope.get("error") is None, envelope.get("error")
    assert envelope.get("disclosure") is not None, "a success must carry the mandatory disclosure"
    receipt = envelope["result"]
    assert receipt["created"] is True

    assert runtime.principal is not None
    with runtime.work_engine.begin() as connection:
        stored = connection.execute(
            text(
                "SELECT c.capture_id, c.owner_principal_id, r.idempotency_key "
                "FROM knowledge.capture_receipts r "
                "JOIN knowledge.capture_versions v ON v.version_id = r.version_id "
                "JOIN knowledge.captures c ON c.capture_id = v.capture_id "
                "WHERE r.receipt_id = :receipt_id"
            ),
            {"receipt_id": receipt["receipt_id"]},
        ).one_or_none()
    assert stored is not None, (
        "the gateway answered with a receipt that names no row; a 200 is not persistence"
    )
    assert stored.capture_id == receipt["capture_id"]
    assert stored.idempotency_key == "bff-chain-1"
    assert stored.owner_principal_id == runtime.principal.principal_id


def test_a_foreign_principal_in_the_envelope_reaches_nothing(
    wire: Wire, runtime: GatewayRuntime, contract: dict[str, Any]
) -> None:
    """A stated foreign identity is ignored: same acting principal, same partition.

    Asserted on the result *and* on the database, because either alone is weak. A
    result-only assertion would pass against a build that stored the foreign
    identifier and read it back; a database-only assertion would pass against one
    that refused the request outright, which is a different behaviour from
    ignoring the field.
    """
    reply = wire.send(
        "capture.create",
        bff_document(
            contract,
            "capture.create",
            {"text": "a synthetic note under a foreign envelope", "idempotency_key": "bff-chain-2"},
            principal_id=FOREIGN_PRINCIPAL,
        ),
    )
    assert reply.status == 200, reply.rendered()
    envelope = reply.document()
    assert envelope.get("error") is None, envelope.get("error")
    receipt = envelope["result"]

    assert runtime.principal is not None
    acting = runtime.principal.principal_id
    assert acting != FOREIGN_PRINCIPAL

    with runtime.work_engine.begin() as connection:
        owner = connection.execute(
            text(
                "SELECT owner_principal_id FROM knowledge.captures WHERE capture_id = :capture_id"
            ),
            {"capture_id": receipt["capture_id"]},
        ).scalar_one()
        foreign_rows = (
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.captures WHERE owner_principal_id = :foreign "
                    "UNION ALL SELECT count(*) FROM knowledge.capture_versions "
                    "WHERE owner_principal_id = :foreign "
                    "UNION ALL SELECT count(*) FROM knowledge.audit_events "
                    "WHERE principal_id = :foreign"
                ),
                {"foreign": FOREIGN_PRINCIPAL},
            )
            .scalars()
            .all()
        )
    assert owner == acting, (
        "the capture was stored under the principal the envelope named, which would mean "
        "metadata.principal_id had become an authority"
    )
    assert set(foreign_rows) == {0}, "the foreign identifier reached a stored row"

    # And the read side: a listing sent under the foreign envelope is the acting
    # principal's own, not an empty page and not somebody else's.
    listing = wire.send(
        "capture.list",
        bff_document(contract, "capture.list", {"page_size": 25}, principal_id=FOREIGN_PRINCIPAL),
    )
    assert listing.status == 200, listing.rendered()
    captures = listing.document()["result"]["captures"]
    assert captures, "the listing was empty, so it proves nothing about whose captures it returned"
    assert {entry["owner_principal_id"] for entry in captures} == {acting}
    assert all(FOREIGN_PRINCIPAL not in json.dumps(entry) for entry in captures)


def test_the_review_listing_the_bff_calls_answers_over_the_same_chain(
    wire: Wire, contract: dict[str, Any]
) -> None:
    """`review.list` is reachable and contract-shaped, on an empty plane.

    Empty is the honest state for a database with no proposals in it, and the
    assertion is on the *shape* rather than on a count: the envelope carries the
    mandatory disclosure and a `review_cases` key, which is what the BFF route
    reads. A test asserting rows here would be asserting a fixture the plane does
    not have.
    """
    reply = wire.send(
        "review.list",
        bff_document(contract, "review.list", {"page_size": 25}, principal_id=SESSION_CORRELATION),
    )
    assert reply.status == 200, reply.rendered()
    envelope = reply.document()
    assert envelope.get("error") is None, envelope.get("error")
    assert envelope["disclosure"]["coverage"]["state"] == "not_enrolled"
    assert envelope["result"]["review_cases"] == []


def test_capabilities_get_reports_the_manifest_the_system_route_publishes(
    wire: Wire, contract: dict[str, Any]
) -> None:
    """`capabilities.get` answers with the manifest and readiness `/api/system` reads."""
    reply = wire.send(
        "capabilities.get",
        bff_document(contract, "capabilities.get", {}, principal_id=SESSION_CORRELATION),
    )
    assert reply.status == 200, reply.rendered()
    result = reply.document()["result"]
    assert {status["name"] for status in result["manifest"]["capabilities"]} >= set(
        contract["capabilities"]
    ), "the manifest does not name every capability the BFF is allowed to address"
    assert result["readiness"]["implemented_capabilities"] > 0
