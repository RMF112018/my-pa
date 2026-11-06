"""Reports Modernization WP05b Part C layers 10-11: the custody names through the compact facade.

On `tests/contract/test_reports_compact_facade.py`'s harness: the real remote
MCP app over httpx's ASGI transport, the real `RemoteAuthenticator` over the
durable grant store on PostgreSQL, the composition root's
`remote_access_context` and a real `ApplicationService`. The four operator
custody capabilities (`reports.hold.place`, `reports.hold.release`,
`reports.retention.set`, `reports.retention.get`) are operator-only and attested
to the local operator surface (operator decision 2026-11-05, H1):

* the `my_pa.describe` catalog never lists them, `my_pa.describe` naming one is
  `unsupported`, and `my_pa.write` / `my_pa.read` / `my_pa.operator` naming one
  is `unsupported`;
* a FORGED active grant row for the exact purpose (`report_hold` /
  `report_retention`) inserted for the client changes none of that, and writes
  nothing: the hold ledger, the retention history, the root hold cache and the
  lifecycle events are exactly as they were;
* a client with the full ordinary Reports grants still reads a held report
  (`"held": true` on `reports.read` and `reports.history`), archives and
  restores it, and its `reports.delete` is `denied [report_held]` with no
  lifecycle row (H2);
* `held`, `hold_revision` and `hold_event_id` forged into an ordinary payload
  are refused before any mutation.

The hold itself is placed the only way it can be: through the service on the
local operator surface (`OperatorSurface.CLI`) with a preservation store under
`tmp_path`. Every identity, title and body is synthetic.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.conftest import DEFAULT_LIMITS, metadata_for
from tests.contract.test_reports_compact_facade import (
    ARCHIVE,
    CLIENT,
    DELETE,
    HISTORY,
    INTELLIGENCE_TABLES,
    MINIMAL,
    MUTATION_TABLES,
    PUBLISH,
    READ,
    RESTORE,
    UPDATE,
    WHEN,
    Harness,
    build_service,
    counts,
    describe,
    grant_row,
    move_payload,
    ok,
    outcome,
    profile_grants,
    refusal,
    remote_principal,
    update_payload,
    wrapped,
)

from my_pa.adapters.mcp.chatllm_gateway import OPERATOR_TOOL, READ_TOOL, WRITE_TOOL
from my_pa.adapters.normalization import normalize
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ReportContentNamespace
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore

pytestmark = pytest.mark.database

HOLD_PLACE: Final = Capability.REPORTS_HOLD_PLACE
HOLD_RELEASE: Final = Capability.REPORTS_HOLD_RELEASE
RETENTION_SET: Final = Capability.REPORTS_RETENTION_SET
RETENTION_GET: Final = Capability.REPORTS_RETENTION_GET
CUSTODY: Final = (HOLD_PLACE, HOLD_RELEASE, RETENTION_SET, RETENTION_GET)
CUSTODY_WRITES: Final = (HOLD_PLACE, HOLD_RELEASE, RETENTION_SET)
CUSTODY_TABLES: Final = ("report_hold_events", "report_retention_policy_events")
_ALL_TABLES: Final = (*MUTATION_TABLES, *CUSTODY_TABLES, *INTELLIGENCE_TABLES)
_HOLD_REASON: Final = "Synthetic litigation hold."


@pytest.fixture
def harness(migrated_engine: Engine) -> Harness:
    built = Harness(migrated_engine, build_service(migrated_engine))
    built.gates()
    return built


def _forged(capability: Capability) -> tuple[Any, ...]:
    """An active grant row for the capability's exact (and only) purpose."""
    (purpose,) = permitted_purposes(capability)
    return grant_row(capability, purpose=purpose, is_write=capability in CUSTODY_WRITES)


def _hold_cache(engine: Engine) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT report_id, held, hold_revision, hold_event_id "
                "FROM knowledge.report_roots ORDER BY report_id"
            )
        ).all()
    return [tuple(row) for row in rows]


def _snapshot(engine: Engine) -> tuple[dict[str, int], list[tuple[Any, ...]]]:
    return counts(engine, _ALL_TABLES), _hold_cache(engine)


def _payload(capability: Capability, report_id: str) -> dict[str, Any]:
    """A payload the canonical schema of `capability` accepts."""
    if capability in (HOLD_PLACE, HOLD_RELEASE):
        return {"report_id": report_id, "expected_hold_revision": 0, "reason": _HOLD_REASON}
    if capability is RETENTION_SET:
        return {
            "expected_policy_revision": 0,
            "reason": "Synthetic retention.",
            "period": {"count": 5, "unit": "years"},
        }
    return {"report_id": report_id}


def _wrapper(capability: Capability) -> str:
    return READ_TOOL if capability is RETENTION_GET else WRITE_TOOL


def _custody_is_withheld(
    harness: Harness, token: str, report_id: str, *, writes: bool = True
) -> None:
    """Absent from the catalog; describe, read, write and operator naming one are `unsupported`."""
    before = _snapshot(harness.engine)
    requests: list[tuple[str, Mapping[str, Any]]] = [
        (token, describe(limit=100)),
        (token, describe(feature="reports", limit=100)),
    ]
    for capability in CUSTODY:
        payload = _payload(capability, report_id)
        requests += [
            (token, describe(capability=capability.value)),
            (token, wrapped(WRITE_TOOL, capability, payload)),
            (token, wrapped(READ_TOOL, capability, payload)),
            (token, wrapped(OPERATOR_TOOL, capability, payload)),
        ]
    answers = harness.run(requests)
    for listed in answers[:2]:
        _failed, catalog = outcome(listed)
        seen = {item["capability"] for item in catalog["items"]}
        assert not seen & {capability.value for capability in CUSTODY}, seen
        # Non-vacuous: the ordinary report names are listed to the same client.
        assert READ.value in seen
        assert (DELETE.value in seen) is writes
    for answer in answers[2:]:
        assert refusal(answer) == ("unsupported", []), answer.document
    assert _snapshot(harness.engine) == before


def _publish(harness: Harness, token: str) -> str:
    (published,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL))])
    return str(ok(published)["report_id"])


def test_the_custody_names_are_withheld_from_an_ordinary_profile_client(
    harness: Harness,
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    report_id = _publish(harness, token)
    _custody_is_withheld(harness, token, report_id)


def test_the_custody_names_are_withheld_with_the_client_write_flag_off(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service), writes=False)
    _custody_is_withheld(harness, token, "grpt_00000000nothere0", writes=False)


def test_a_forged_custody_grant_is_still_withheld_and_writes_nothing(harness: Harness) -> None:
    """Forged active grants for `report_hold` / `report_retention`: still `unsupported`."""
    publisher = harness.client("synthetic-custody-publisher", profile_grants(harness.service))
    report_id = _publish(harness, publisher)
    forged = tuple(_forged(capability) for capability in CUSTODY)
    token = harness.client(CLIENT, (*profile_grants(harness.service), *forged))
    _custody_is_withheld(harness, token, report_id)


def test_a_client_holding_only_forged_custody_grants_is_withheld(harness: Harness) -> None:
    token = harness.client(CLIENT, tuple(_forged(capability) for capability in CUSTODY))
    before = _snapshot(harness.engine)
    requests: list[tuple[str, Mapping[str, Any]]] = [(token, describe(limit=100))]
    for capability in CUSTODY:
        payload = _payload(capability, "grpt_00000000nothere0")
        requests += [
            (token, describe(capability=capability.value)),
            (token, wrapped(_wrapper(capability), capability, payload)),
        ]
    listed, *refused = harness.run(requests)
    # Nothing is published to this client at all: even the catalog is refused.
    assert refusal(listed) == ("unsupported", [])
    for answer in refused:
        assert refusal(answer) == ("unsupported", []), answer.document
    assert _snapshot(harness.engine) == before


# ---- a held report through the ordinary grants -----------------------------------


def _operator_service(engine: Engine, root: Path) -> ApplicationService:
    """The local operator's service with a preservation store: the one way to place a hold."""
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        report_preservation_store=FilesystemReportContentStore(
            root, ReportContentNamespace.PRESERVATION
        ),
    )


def _place_hold_locally(engine: Engine, root: Path, report_id: str) -> dict[str, Any]:
    principal = remote_principal()
    _metadata, command = normalize(
        HOLD_PLACE.value,
        {
            "request_id": "req-custody-facade-hold",
            "purpose": Purpose.REPORT_HOLD.value,
            "principal_id": principal.principal_id,
            "requested_at": "2026-11-04T12:00:00Z",
            "payload": {
                **_payload(HOLD_PLACE, report_id),
                "idempotency_key": "custody-facade-hold",
            },
        },
    )
    envelope = _operator_service(engine, root).invoke(
        metadata_for(HOLD_PLACE, Purpose.REPORT_HOLD, principal),
        command,
        principal=principal,
        operator_surface=OperatorSurface.CLI,
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    assert envelope.result["held"] is True
    return dict(envelope.result)


def test_an_ordinary_client_reads_archives_and_restores_a_held_report_but_cannot_trash_it(
    harness: Harness, tmp_path: Path
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    report_id = _publish(harness, token)
    (unheld,) = harness.run([(token, wrapped(READ_TOOL, READ, {"report_id": report_id}))])
    assert ok(unheld)["held"] is False

    root = tmp_path / "report-content"
    root.mkdir(mode=0o700)
    placed = _place_hold_locally(harness.engine, root, report_id)
    assert placed["hold_revision"] == 1

    read, history = harness.run(
        [
            (token, wrapped(READ_TOOL, READ, {"report_id": report_id})),
            (token, wrapped(READ_TOOL, HISTORY, {"report_id": report_id})),
        ]
    )
    assert ok(read)["held"] is True
    assert ok(history)["held"] is True
    # Only the boolean: never the reason, the actor or the seal.
    for answer in (read, history):
        body = str(outcome(answer)[1])
        assert _HOLD_REASON not in body
        assert placed["event_id"] not in body
        assert placed["preservation"]["seal_object_id"] not in body

    archived, restored = harness.run(
        [
            (token, wrapped(WRITE_TOOL, ARCHIVE, move_payload(report_id, 0))),
            (token, wrapped(WRITE_TOOL, RESTORE, move_payload(report_id, 1))),
        ]
    )
    assert ok(archived)["lifecycle_state"] == "archived"
    assert ok(restored)["lifecycle_state"] == "active"

    before = _snapshot(harness.engine)
    (deleted,) = harness.run([(token, wrapped(WRITE_TOOL, DELETE, move_payload(report_id, 2)))])
    assert refusal(deleted) == ("denied", ["report_held"])
    assert _snapshot(harness.engine) == before
    # The custody names stay withheld from this client while the report is held.
    _custody_is_withheld(harness, token, report_id)


# ---- forged hold fields on the ordinary capabilities ------------------------------

_HOLD_FIELDS: Final[Mapping[str, Any]] = {
    "held": False,
    "hold_revision": 0,
    "hold_event_id": "grhld_00000000forged00",
}


@pytest.mark.parametrize("name", sorted(_HOLD_FIELDS))
def test_a_forged_hold_field_on_an_ordinary_capability_is_refused(
    harness: Harness, name: str
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    report_id = _publish(harness, token)
    forged = {name: _HOLD_FIELDS[name]}
    before = _snapshot(harness.engine)
    answers = harness.run(
        [
            (token, wrapped(WRITE_TOOL, PUBLISH, {**MINIMAL, **forged})),
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    UPDATE,
                    update_payload(report_id, 1, {"title": "Synthetic forged"}, **forged),
                ),
            ),
            (token, wrapped(WRITE_TOOL, ARCHIVE, move_payload(report_id, 0, **forged))),
            (token, wrapped(WRITE_TOOL, DELETE, move_payload(report_id, 0, **forged))),
            (token, wrapped(WRITE_TOOL, RESTORE, move_payload(report_id, 0, **forged))),
            (token, wrapped(READ_TOOL, READ, {"report_id": report_id, **forged})),
            (token, wrapped(READ_TOOL, HISTORY, {"report_id": report_id, **forged})),
        ]
    )
    for answer in answers:
        assert refusal(answer)[0] == "invalid_request", answer.document
    assert _snapshot(harness.engine) == before
