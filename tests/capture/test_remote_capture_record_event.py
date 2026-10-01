"""WP-RE-08 RE-AC-093: a remote-client capture commits the same Record Event.

Against real PostgreSQL and through the real composition, with the ingress
turned on. A registered client posts to `/remote/v1/capture.create` (transport
`remote_client`); the capture reaches `capture.create` through the same
`ApplicationService.invoke`, so it must commit the same one `capture` `created`
event -- in the same durable transaction as the capture rows (equal `xmin`),
never in a parallel one. A retry over the ingress replays and commits nothing.

The database is the package's disposable clone. Every value is synthetic and the
only socket bound is a loopback one.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, text
from tests.capture.test_remote_capture_is_one_durable_transaction import document, mint, submit
from tests.wire import serve

from my_pa.adapters.http import create_http_app
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings


@pytest.fixture
def serving(capture_database: str) -> Iterator[GatewayRuntime]:
    """The composition with the ingress turned on, over the disposable clone."""
    built = build_gateway_runtime(
        Settings(database_url=capture_database, remote_ingress_enabled=True)
    )
    try:
        assert built.remote_client is not None, "the ingress was composed off"
        yield built
    finally:
        built.close()


def _capture_events(engine: Engine, principal_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT e.*, e.xmin::text AS tx FROM knowledge.record_events e "
                    "WHERE e.principal_id = :principal AND e.record_family = 'capture' "
                    "ORDER BY e.sequence_number"
                ),
                {"principal": principal_id},
            ).mappings()
        ]


def _version_tx(engine: Engine, version_id: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT xmin::text FROM knowledge.capture_versions WHERE version_id = :v"),
                {"v": version_id},
            ).scalar_one()
        )


@pytest.mark.database
def test_a_remote_capture_commits_one_created_event_in_its_own_transaction(
    serving: GatewayRuntime,
) -> None:
    credential = mint(serving)
    principal_id = serving.principal.principal_id
    # INFO-2: the package database is shared and the feed is never truncated,
    # so everything is asserted relative to what this Principal held before.
    before = _capture_events(serving.work_engine, principal_id)
    with serve(
        create_http_app(
            serving.service, principal=serving.principal, remote_client=serving.remote_client
        )
    ) as wire:
        answer = submit(wire, credential, document("wp08-remote-key"))
        assert answer.status == 200, answer.body
        retry = submit(wire, credential, document("wp08-remote-key"))
        assert retry.status == 200, retry.body
    remote = answer.document()["result"]
    assert remote["created"] is True
    assert retry.document()["result"]["created"] is False

    events = _capture_events(serving.work_engine, principal_id)[len(before) :]
    assert [e["event_id"] for e in _capture_events(serving.work_engine, principal_id)][
        : len(before)
    ] == [e["event_id"] for e in before]
    assert len(events) == 1, events
    event = events[0]
    assert event["record_id"] == remote["capture_id"]
    assert event["event_kind"] == "created"
    assert event["record_version"] == 1
    assert event["source_receipt_id"] == remote["receipt_id"]
    assert event["source_capability"] == "capture.create"
    assert event["actor_class"] == "principal"
    assert event["tx"] == _version_tx(serving.work_engine, str(remote["version_id"])), (
        "the event and the capture version must commit in one transaction"
    )
    with serving.work_engine.connect() as connection:
        transport = connection.execute(
            text("SELECT transport FROM knowledge.capture_submissions WHERE receipt_id = :receipt"),
            {"receipt": remote["receipt_id"]},
        ).scalar_one()
    assert transport == "remote_client"
