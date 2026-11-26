"""WP5-S5: the wired `meetings.context.read` over PostgreSQL.

The `database` tier, on a disposable current-head clone: the synthetic world of
`tests/database/test_meeting_context_communications.py`, read through
`ApplicationService` with `MY_PA_COMMUNICATIONS_ENABLED` on, in the
invocation's own unit of work (the handler never opens a second one). The
answer is the read service's own payload; a foreign Principal's Meeting is
`not_found`; with the switch off the same request is the standard
`unsupported`, whatever the project-report switch says (ruling Q4). The
gateway test (the Schedule T2-25 / WP4-R2 G3 model) proves a restricted MCP
database role composition never serves the name, whatever the switch. Every
value is synthetic.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.engine import Connection

from my_pa.adapters.normalization import normalize
from my_pa.application.meeting_context import context_payload
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS
from tests.contract.test_transport_parity import document
from tests.database.communications_search_world import NOW, at
from tests.database.test_meeting_context_communications import A, B, Scene, scene

pytestmark = pytest.mark.database

__all__ = ["scene"]

NAME: Final = "meetings.context.read"


def _service(
    engine: Engine, *, communications: bool, project_reports: bool = False
) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)),
        limits=DEFAULT_LIMITS,
        clock=lambda: NOW,
        communications_enabled=communications,
        project_reports_enabled=project_reports,
    )


def _invoke(
    service: ApplicationService, principal_id: str, payload: dict[str, Any]
) -> ResponseEnvelope:
    principal = Principal(principal_id, PrincipalKind.OPERATOR, authenticated=True)
    metadata, command = normalize(NAME, document(Capability(NAME), principal_id, payload))
    return service.invoke(metadata, command, principal=principal)


def test_the_wired_read_answers_through_the_service_in_its_own_unit_of_work(
    scene: Scene,
) -> None:
    w = scene.mail
    hit = w.message(
        1,
        subject="Slab pour RFI 174",
        text="Per RFI 174 the slab pour moves.",
        when=at(17, 10),
        participants=(("from", A), ("to", B)),
    )
    meeting = scene.meeting("wired", title="Slab pour", emails=(A, B), description="See RFI 174")
    theirs = scene.meeting("wired-theirs", principal_id=scene.theirs.principal.principal_id)
    engine = scene.engine
    service = _service(engine, communications=True)
    begins: list[object] = []

    def record(connection: Connection) -> None:
        begins.append(connection)

    event.listen(engine, "begin", record)
    try:
        # The baseline: a WP4 read in its invocation's unit of work (the
        # invocation's transaction and the audit sink's own).
        baseline = service.invoke(
            *normalize(
                "communications.coverage",
                document(
                    Capability.COMMUNICATIONS_COVERAGE,
                    scene.principal_id,
                    {"from_utc": "2026-11-17T00:00:00Z", "to_utc": "2026-11-18T00:00:00Z"},
                ),
            ),
            principal=Principal(scene.principal_id, PrincipalKind.OPERATOR, authenticated=True),
        )
        assert baseline.error is None
        expected = len(begins)
        begins.clear()
        answer = _invoke(service, scene.principal_id, {"meeting_ids": [meeting, theirs]})
    finally:
        event.remove(engine, "begin", record)
    assert answer.error is None, answer.error
    payload = answer.result
    assert payload is not None
    # The handler opens no transaction of its own beyond the invocation's.
    assert len(begins) == expected
    # The answer is the read service's own payload, byte for byte.
    direct = context_payload(scene.read([meeting, theirs]))
    assert payload == direct
    assert payload["not_found"] == [theirs]
    (context,) = payload["meetings"]
    assert context["meeting"]["meeting_id"] == meeting
    assert context["communications"]["messages"][0]["message_id"] == hit
    assert context["pulse"] == {"state": "unavailable", "reason": "reads_disabled"}
    assert answer.disclosure is not None
    assert answer.disclosure.trust.basis == ("principal_partition",)
    # The project-report switch is passed through to the `pulse` section.
    linked = _invoke(
        _service(engine, communications=True, project_reports=True),
        scene.principal_id,
        {"meeting_ids": [meeting]},
    )
    assert linked.error is None and linked.result is not None
    assert linked.result["meetings"][0]["pulse"] == {"state": "not_linked"}
    # A foreign Principal reads nothing of mine.
    foreign = _invoke(
        _service(engine, communications=True),
        scene.theirs.principal.principal_id,
        {"meeting_ids": [meeting]},
    )
    assert foreign.error is None and foreign.result is not None
    assert (foreign.result["meetings"], foreign.result["not_found"]) == ([], [meeting])
    for project_reports in (False, True):
        off = _invoke(
            _service(engine, communications=False, project_reports=project_reports),
            scene.principal_id,
            {"meeting_ids": [meeting]},
        )
        assert off.error is not None and off.error.code.value == "unsupported"


def test_a_restricted_profile_composition_never_serves_the_context_read(
    cloned_database_url: str, migrated_engine: Engine
) -> None:
    """The Schedule T2-25 / WP4-R2 G3 model: the MCP database roles hold no
    privilege on the communications tables, so the gateway composes the
    communications switch only without an injected `data_engine`. A profile
    service never serves the name, even with the switch on; the full-role
    control service does.
    """
    from my_pa.bootstrap.gateway import build_gateway_runtime
    from my_pa.bootstrap.settings import Settings

    settings = Settings(
        database_url=cloned_database_url, communications_enabled=True, project_reports_enabled=True
    )
    control = build_gateway_runtime(settings)
    profile = build_gateway_runtime(
        settings,
        data_engine=migrated_engine,
        independent_audit_engine=control.audit_engine,
        controls_engine=control.work_engine,
        permit_reenrichment=False,
        permit_managed_documents=False,
    )
    try:
        assert NAME in {c.value for c in control.service.available_capabilities}
        assert NAME not in {c.value for c in profile.service.available_capabilities}
    finally:
        for engine in {control.work_engine, control.audit_engine}:
            engine.dispose()
