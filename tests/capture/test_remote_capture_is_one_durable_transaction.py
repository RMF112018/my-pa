"""A remote submission is the same durable transaction, not a parallel one.

WP-10's first and third controls, against real PostgreSQL and through the real
composition. The claim is not "the remote path also works" — it is that there is
**no remote path**: an authenticated ingress request reaches `capture.create`
through `ApplicationService.invoke`, the same `authorize`, the same
`admit_capture`, the same four inserts in the same transaction, the same unique
index, and the same receipt.

**How that is proved is by difference rather than by inspection.** Two captures
are made — one over `/v1/capture.create` as the local operator, one over the
ingress as a registered client — with byte-identical text and equivalent
requests. Every row both wrote is read back and compared column by column, with
the values that are *supposed* to differ (identifiers, digests of different keys,
timestamps written by the server) removed by name. What is left has to be equal,
and the two columns that differ are named in advance: `transport` and
`trust_state`. A test that merely asserted "a remote capture is readable" would
pass against a second, parallel writer.

**The control that makes the equality mean something** is that the two rows are
*not* trivially equal: the assertion below requires `transport` to differ, so a
comparison that had accidentally collapsed to comparing one row with itself
fails rather than passing.

Idempotent replay and the changed-payload conflict are here too, because
`QC-AC-031`/`QC-AC-032` are properties of the unique index and the ingress has to
inherit them rather than reimplement them — and the sharpest form of that is a
retry that arrives over a *different* transport and still replays.

The database is disposable, created and dropped by this package's fixture, and
never the configured one. Every value is synthetic and the only socket bound is
a loopback one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.capture.conftest import WHEN, invoke, succeeded
from tests.wire import Reply, Wire, serve

from my_pa.adapters.http import REMOTE_CAPTURE_CAPABILITY, REMOTE_CAPTURE_PATH, create_http_app
from my_pa.application.commands import CreateCapture
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.client import issue_client_secret
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.capture_clients import register_client
from my_pa.infrastructure.persistence.principal_scope import capture_context

#: The one note both submissions carry, byte for byte. Synthetic, and distinctive
#: enough that finding it anywhere is finding this text.
NOTE: Final = "a synthetic note that both transports submit, verbatim"

WHEN_WIRE: Final = "2026-08-03T12:00:00Z"

#: Columns whose values are expected to differ between two independent
#: admissions of the same text, and which therefore say nothing about whether the
#: two took the same path. Every one is either a server-issued identifier, a
#: digest of a per-request key, or a clock reading.
_INCIDENTAL: Final = frozenset(
    {
        "accepted_at",
        "audit_id",
        "capture_id",
        "client_id",
        "correlation_id",
        "created_at",
        "idempotency_key",
        "issued_at",
        "next_attempt_at",
        "operation_id",
        "payload_sha256",
        "receipt_id",
        "recorded_at",
        "request_id",
        "server_received_at",
        "submission_id",
        "updated_at",
        "version_id",
    }
)

#: The columns a remote submission is *supposed* to differ in. Named in advance,
#: so the comparison below is an equality with two declared exceptions rather
#: than a diff somebody reads.
_PROVENANCE: Final = frozenset({"transport", "trust_state"})


@pytest.fixture
def serving(capture_database: str) -> Iterator[GatewayRuntime]:
    """The composition with the ingress turned on, over the disposable database."""
    built = build_gateway_runtime(
        Settings(database_url=capture_database, remote_ingress_enabled=True)
    )
    try:
        with built.work_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.captures, knowledge.capture_versions, "
                    "knowledge.capture_receipts, knowledge.capture_submissions, "
                    "knowledge.capture_jobs, knowledge.capture_clients, "
                    "knowledge.audit_events CASCADE"
                )
            )
        assert built.remote_client is not None, "the ingress was composed off"
        yield built
    finally:
        built.close()


def mint(runtime: GatewayRuntime) -> str:
    """One registered client for the runtime's own Principal, as its credential.

    Minted through the same writer `apps/cli/clients.py` calls, so the secret
    this test presents is one the production path could have produced.
    """
    assert runtime.principal is not None
    secret, digest = issue_client_secret()
    with runtime.work_engine.begin() as connection:
        client = register_client(
            connection,
            secret_sha256=digest,
            at=datetime.now(UTC),
            context=capture_context(runtime.principal.principal_id),
        )
    return f"ClientCredential {client.client_id}:{secret}"


def document(key: str, *, text_value: str = NOTE) -> dict[str, Any]:
    """The canonical request an iOS Shortcut would post: an envelope and a payload.

    It names no `principal_id`, which is the ingress contract, and it is
    otherwise the document every other transport sends.
    """
    return {
        "request_id": f"req-remote-{key}",
        "purpose": Purpose.CAPTURE_AUTHORING.value,
        "requested_at": WHEN_WIRE,
        "payload": {"text": text_value, "idempotency_key": key},
    }


def submit(wire: Wire, credential: str, body: Mapping[str, Any]) -> Reply:
    return wire.send(
        REMOTE_CAPTURE_CAPABILITY,
        dict(body),
        path=REMOTE_CAPTURE_PATH,
        extra_headers={"authorization": credential},
    )


def _rows(engine: Engine, table: str) -> list[dict[str, Any]]:
    """Every row of one table, rendered whole, so a new column is compared too."""
    with engine.connect() as connection:
        return [
            json.loads(str(row[0]))
            # S608: `table` is a literal from this module; nothing here is input.
            for row in connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t"))  # noqa: S608
        ]


def _comparable(row: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in row.items() if name not in _INCIDENTAL}


@pytest.mark.database
def test_a_remote_submission_writes_the_same_rows_as_a_local_one(
    serving: GatewayRuntime,
) -> None:
    """Control 1, as a column-by-column comparison of two real admissions.

    The local capture goes through `ApplicationService.invoke` directly, the way
    every other module in this package drives it; the remote one goes over a
    socket, through the ingress, with a credential. Both write a capture, a
    version, a receipt, a submission and a queued job, and everything about those
    rows that is not a per-request identifier, digest, or clock reading is equal.
    """
    credential = mint(serving)
    local = succeeded(
        invoke(
            serving,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=NOTE, idempotency_key="local-key"),
            "local",
        ),
        "the local capture",
    )
    with serve(
        create_http_app(
            serving.service, principal=serving.principal, remote_client=serving.remote_client
        )
    ) as wire:
        answer = submit(wire, credential, document("remote-key"))
    assert answer.status == 200, answer.body
    remote = answer.document()["result"]

    assert local["created"] is True and remote["created"] is True
    assert local["content_sha256"] == remote["content_sha256"], (
        "the two submissions carried the same text and must digest to the same value"
    )

    for table in (
        "knowledge.captures",
        "knowledge.capture_versions",
        "knowledge.capture_receipts",
        "knowledge.capture_jobs",
    ):
        rows = _rows(serving.work_engine, table)
        assert len(rows) == 2, f"{table} holds {len(rows)} rows, not one per submission"
        first, second = (_comparable(row) for row in rows)
        assert first == second, (
            f"{table} distinguishes a remote submission from a local one. The "
            "remote path is meant to reach the same durable transaction, so "
            "nothing outside `capture_submissions` may differ"
        )


@pytest.mark.database
def test_the_submission_row_differs_in_exactly_the_two_provenance_columns(
    serving: GatewayRuntime,
) -> None:
    """The transport is recorded as provenance, and as *only* provenance.

    `capture_submissions` is the one table that differs, and it differs in
    `transport` and `trust_state` and in nothing else. The inequality assertion
    is the control: if the two rows were identical the comparison above would be
    comparing a row with itself and would pass on a build that recorded no
    provenance at all.
    """
    credential = mint(serving)
    succeeded(
        invoke(
            serving,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=NOTE, idempotency_key="local-key"),
            "local",
        ),
        "the local capture",
    )
    with serve(
        create_http_app(
            serving.service, principal=serving.principal, remote_client=serving.remote_client
        )
    ) as wire:
        admitted = submit(wire, credential, document("remote-key"))
        assert admitted.status == 200

    rows = _rows(serving.work_engine, "knowledge.capture_submissions")
    assert len(rows) == 2
    by_transport = {row["transport"]: row for row in rows}
    assert set(by_transport) == {"local", "remote_client"}, (
        f"the two submissions recorded {sorted(by_transport)}; the remote one has "
        "to say so, and the local one must not"
    )
    assert by_transport["local"]["trust_state"] == "local_principal"
    assert by_transport["remote_client"]["trust_state"] == "registered_client"

    differing = {
        name
        for name in _comparable(rows[0])
        if _comparable(rows[0])[name] != _comparable(rows[1])[name]
    }
    assert differing == _PROVENANCE, (
        f"the two submission rows differ in {sorted(differing)}; exactly "
        f"{sorted(_PROVENANCE)} were declared, and anything else is a second data "
        "model rather than provenance"
    )


@pytest.mark.database
def test_the_remote_capture_reads_back_through_the_ordinary_capability(
    serving: GatewayRuntime,
) -> None:
    """It is one corpus. A remotely captured note is read by `capture.read`.

    Not decoration: a parallel writer that produced its own rows would still fail
    to be readable through the capability that reads the real ones, and a build
    that stored nothing at all would fail here rather than passing every absence
    assertion in the module.
    """
    credential = mint(serving)
    with serve(
        create_http_app(
            serving.service, principal=serving.principal, remote_client=serving.remote_client
        )
    ) as wire:
        answer = submit(wire, credential, document("remote-key"))
    assert answer.status == 200, answer.body
    receipt = answer.document()["result"]

    from my_pa.application.commands import ReadCapture

    read = succeeded(
        invoke(
            serving,
            Capability.CAPTURE_READ,
            ReadCapture(capture_id=receipt["capture_id"]),
            "read-remote",
        ),
        "reading the remote capture back",
    )
    assert read["text"] == NOTE
    assert read["owner_principal_id"] == serving.principal.principal_id


@pytest.mark.database
def test_a_replayed_remote_submission_returns_the_same_receipt_and_stores_nothing_new(
    serving: GatewayRuntime,
) -> None:
    """Control 3, on the real unique index rather than on a check in Python.

    The same key with the same text is `QC-AC-031`'s replay: the byte-identical
    receipt with `created: false`, and not one extra row anywhere.
    """
    credential = mint(serving)
    with serve(
        create_http_app(
            serving.service, principal=serving.principal, remote_client=serving.remote_client
        )
    ) as wire:
        first = submit(wire, credential, document("retry-key"))
        second = submit(wire, credential, document("retry-key"))

    assert first.status == 200 and second.status == 200, second.body
    original = first.document()["result"]
    replayed = second.document()["result"]
    assert original["created"] is True
    assert replayed["created"] is False
    assert {k: v for k, v in original.items() if k != "created"} == {
        k: v for k, v in replayed.items() if k != "created"
    }, "a replay returned a different receipt; the caller cannot tell which is real"

    for table in (
        "knowledge.captures",
        "knowledge.capture_versions",
        "knowledge.capture_receipts",
        "knowledge.capture_submissions",
        "knowledge.capture_jobs",
    ):
        assert len(_rows(serving.work_engine, table)) == 1, f"{table} gained a row on the replay"


@pytest.mark.database
def test_a_retry_that_changes_the_note_conflicts_rather_than_overwriting(
    serving: GatewayRuntime,
) -> None:
    """Control 3's other half, and the same `409` the web tier already gets (`D-16`).

    Same key, different text: refused with `conflict`, naming the key and
    nothing about either note. The stored version is untouched, which is the part
    that would matter to somebody whose capture had been silently replaced.
    """
    credential = mint(serving)
    with serve(
        create_http_app(
            serving.service, principal=serving.principal, remote_client=serving.remote_client
        )
    ) as wire:
        first = submit(wire, credential, document("conflict-key"))
        clashing = submit(
            wire, credential, document("conflict-key", text_value="a different synthetic note")
        )

    assert first.status == 200, first.body
    assert clashing.status == 409, clashing.body
    problem = clashing.document()["error"]
    assert problem["code"] == ErrorCode.CONFLICT.value
    assert problem["safe_details"] == ["idempotency_key"]
    assert "different synthetic note" not in clashing.rendered()

    versions = _rows(serving.work_engine, "knowledge.capture_versions")
    assert len(versions) == 1
    assert versions[0]["content"] == NOTE


@pytest.mark.database
def test_a_retry_arriving_over_the_other_transport_still_replays(
    serving: GatewayRuntime,
) -> None:
    """The sharpest form of control 3, and the reason the transport is not digested.

    A device that captured over the ingress and then retried from the local
    gateway — or the reverse — is retrying the same request. If `transport` were
    part of the admission digest the second call would be a `409` and the caller
    would be told its own note conflicted with itself. It is not, and this is what
    holds that.
    """
    credential = mint(serving)
    with serve(
        create_http_app(
            serving.service, principal=serving.principal, remote_client=serving.remote_client
        )
    ) as wire:
        remote = submit(wire, credential, document("cross-key"))
    assert remote.status == 200, remote.body

    local = succeeded(
        invoke(
            serving,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=NOTE, idempotency_key="cross-key"),
            "cross",
        ),
        "the local retry of a remote submission",
    )
    assert local["created"] is False
    assert local["receipt_id"] == remote.document()["result"]["receipt_id"]
    assert len(_rows(serving.work_engine, "knowledge.capture_versions")) == 1
    assert WHEN is not None
