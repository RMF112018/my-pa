"""Production event paths must register every governed re-enrichment trigger."""

from __future__ import annotations

import inspect

import pytest

from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.domain.relationship.reenrichment import ReenrichmentTrigger


@pytest.mark.parametrize(
    ("handler_name", "trigger"),
    [
        ("_entities_merge", ReenrichmentTrigger.CORRECTED_IDENTITY),
        ("_entities_split", ReenrichmentTrigger.CORRECTED_IDENTITY),
        ("_entities_aliases_add", ReenrichmentTrigger.NEW_ALIAS),
        ("_entities_relationships_create", ReenrichmentTrigger.PROJECT_MAPPING_CHANGE),
        ("_entities_relationships_revise", ReenrichmentTrigger.PROJECT_MAPPING_CHANGE),
        ("_entities_relationships_end", ReenrichmentTrigger.PROJECT_MAPPING_CHANGE),
        (
            "_entities_assignments_create",
            ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
        ),
        (
            "_entities_assignments_revise",
            ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
        ),
        ("_entities_assignments_end", ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE),
        ("_admit", ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION),
        ("_review_decide", ReenrichmentTrigger.CONTRADICTION_RESOLUTION),
    ],
)
def test_each_production_mutation_path_registers_its_exact_trigger(
    handler_name: str, trigger: ReenrichmentTrigger
) -> None:
    source = inspect.getsource(getattr(ApplicationService, handler_name))
    assert "_register_reenrichment(" in source
    assert f"ReenrichmentTrigger.{trigger.name}" in source


def test_gateway_startup_observes_policy_version() -> None:
    source = inspect.getsource(GatewayRuntime.observe_reenrichment_versions)
    assert "ProductionReenrichmentCaller(" in source
    assert ".observe_process_versions(" in source


def test_production_registration_challenge_covers_the_closed_vocabulary() -> None:
    handler_source = "\n".join(
        inspect.getsource(member)
        for name, member in vars(ApplicationService).items()
        if name.startswith("_") and callable(member)
    )
    source_fetch = inspect.getsource(ApplicationService._sources_fetch)
    proposal_create = inspect.getsource(ApplicationService._entities_proposals_create)
    startup_source = inspect.getsource(GatewayRuntime.observe_reenrichment_versions)
    covered = {
        trigger
        for trigger in ReenrichmentTrigger
        if (
            f"ReenrichmentTrigger.{trigger.name}" in handler_source
            or (
                trigger is ReenrichmentTrigger.SOURCE_VERSION_CHANGE
                and "register_source_version_observation(" in source_fetch
            )
            or (
                trigger is ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE
                and "register_producer_version_observation(" in proposal_create
            )
            or (
                trigger is ReenrichmentTrigger.POLICY_CHANGE
                and ".observe_process_versions(" in startup_source
            )
        )
    }
    assert covered == set(ReenrichmentTrigger)
