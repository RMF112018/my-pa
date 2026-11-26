"""WP4P-S4: the five wired `project_reports.*` reads over PostgreSQL.

The `database` tier, on a disposable head-migrated clone: the synthetic world
of `tests.unit.project_report_reads_scene`, built through the WP3P path, then
read through `ApplicationService` with `MY_PA_PROJECT_REPORTS_ENABLED` on, in
the invocation's own unit of work (the handler never opens a second one). A
foreign Principal's Project is `not_found`; with the switch off the same
request is the standard `unsupported`. The gateway test (the Schedule T2-25
and WP4-R2 G3 model) proves a restricted MCP database role composition never
serves the reads, whatever the switch. The runtime backstop of ruling R2-02
checks every child-table statement the reads send. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine

from my_pa.adapters.normalization import normalize
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS
from tests.contract.test_transport_parity import document
from tests.database.project_report_reads_backstop import Backstop, current_derivations_backstop
from tests.unit.project_report_reads_scene import (
    RFI_PROJECT,
    ReadsScene,
    build_world,
    database_scene,
)

pytestmark = pytest.mark.database

NAMES = {
    "project_reports.catalog",
    "project_reports.query",
    "project_reports.record_history",
    "project_reports.compare",
    "project_reports.coverage",
}
OTHER = "prn_synreadswired0002"


@pytest.fixture(autouse=True)
def _current_derivations_backstop() -> Iterator[Backstop]:
    """Ruling R2-02: every child-table statement the reads send joins the view."""
    with current_derivations_backstop() as seen:
        yield seen


@pytest.fixture
def scene(migrated_engine: Engine) -> ReadsScene:
    built = database_scene(migrated_engine)
    build_world(built)
    return built


def _service(engine: Engine, *, enabled: bool) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)),
        limits=DEFAULT_LIMITS,
        project_reports_enabled=enabled,
    )


def _invoke(
    service: ApplicationService, principal_id: str, name: str, payload: dict[str, Any]
) -> ResponseEnvelope:
    principal = Principal(principal_id, PrincipalKind.OPERATOR, authenticated=True)
    metadata, command = normalize(name, document(Capability(name), principal_id, payload))
    return service.invoke(metadata, command, principal=principal)


def test_the_wired_reads_answer_through_the_service_in_its_own_unit_of_work(
    scene: ReadsScene, migrated_engine: Engine, _current_derivations_backstop: Backstop
) -> None:
    on = _service(migrated_engine, enabled=True)
    me = scene.principal
    project = RFI_PROJECT[1]
    catalog = _invoke(on, me, "project_reports.catalog", {"project_ids": [project]})
    assert catalog.error is None and catalog.result is not None, catalog.error
    (entry,) = catalog.result["projects"]
    series = [s["series_id"] for s in entry["series"]]
    assert series
    query = _invoke(
        on,
        me,
        "project_reports.query",
        {
            "project_id": project,
            "record_family": "rfis",
            "measures": ["open_outstanding.record_count"],
        },
    )
    assert query.error is None and query.result is not None, query.error
    assert query.result["rows"] and query.result["versions"]
    measures = query.result["measures"]
    assert measures and all(m["measure_scope"] == "version" for m in measures)
    history = _invoke(
        on,
        me,
        "project_reports.record_history",
        {"project_id": project, "record_family": "rfis", "identity_key": "rfi:GMP-174"},
    )
    assert history.error is None and history.result is not None, history.error
    (record,) = history.result["records"]
    assert record["observations"]
    compare = _invoke(on, me, "project_reports.compare", {"series_id": series[0]})
    assert compare.error is None and compare.result is not None, compare.error
    coverage = _invoke(on, me, "project_reports.coverage", {"project_ids": [project]})
    assert coverage.error is None and coverage.result is not None, coverage.error
    # Another Principal's Project is not found; the switch off is `unsupported`.
    foreign = _invoke(
        on, OTHER, "project_reports.query", {"project_id": project, "record_family": "rfis"}
    )
    assert foreign.error is not None and foreign.error.code.value == "not_found"
    off = _invoke(
        _service(migrated_engine, enabled=False),
        me,
        "project_reports.query",
        {"project_id": project, "record_family": "rfis"},
    )
    assert off.error is not None and off.error.code.value == "unsupported"
    assert _current_derivations_backstop.checked > 0


def test_a_restricted_profile_composition_serves_no_project_report_read(
    cloned_database_url: str, migrated_engine: Engine
) -> None:
    """The Schedule T2-25 / WP4-R2 G3 model: the MCP database roles hold no
    privilege on the project-report tables, so the gateway composes the read
    switch only without an injected `data_engine`. A profile service serves
    none of the 5 names even with the switch on; the full-role control serves
    all 5.
    """
    from my_pa.bootstrap.gateway import build_gateway_runtime
    from my_pa.bootstrap.settings import Settings

    settings = Settings(database_url=cloned_database_url, project_reports_enabled=True)
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
        assert {c.value for c in control.service.available_capabilities} >= NAMES
        assert not {c.value for c in profile.service.available_capabilities} & NAMES
    finally:
        for engine in {control.work_engine, control.audit_engine}:
            engine.dispose()
