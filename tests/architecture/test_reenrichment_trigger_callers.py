"""Exact RI re-enrichment observers are load-bearing production hooks."""

from __future__ import annotations

import inspect

from my_pa.application.entity_reenrichment import (
    TRIGGERS_BY_MUTATION_CAPABILITY,
    ReenrichmentTrigger,
)
from my_pa.application.service import _DIRECT_REENRICHMENT_CAPABILITIES, ApplicationService

_DIRECT_CALLERS = {
    "capture.revise": (
        "_admit",
        ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION,
    ),
    "entities.aliases.add": ("_entities_aliases_add", ReenrichmentTrigger.NEW_ALIAS),
    "entities.assignments.create": (
        "_entities_assignments_create",
        ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    ),
    "entities.assignments.end": (
        "_entities_assignments_end",
        ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    ),
    "entities.assignments.revise": (
        "_entities_assignments_revise",
        ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    ),
    "entities.merge": ("_entities_merge", ReenrichmentTrigger.CORRECTED_IDENTITY),
    "entities.relationships.create": (
        "_entities_relationships_create",
        ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    ),
    "entities.relationships.end": (
        "_entities_relationships_end",
        ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    ),
    "entities.relationships.revise": (
        "_entities_relationships_revise",
        ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    ),
    "entities.split": ("_entities_split", ReenrichmentTrigger.CORRECTED_IDENTITY),
    "review.decide": ("_review_decide", ReenrichmentTrigger.CONTRADICTION_RESOLUTION),
}


def test_source_and_producer_proxy_mutations_are_not_mapped() -> None:
    assert "sources.enroll" not in TRIGGERS_BY_MUTATION_CAPABILITY
    assert "entities.proposals.create" not in TRIGGERS_BY_MUTATION_CAPABILITY


def test_verified_source_fetch_calls_the_exact_version_observer() -> None:
    source = inspect.getsource(ApplicationService._sources_fetch)
    assert "observed.version_id != content.version_id" in source
    assert "register_source_version_observation(" in source
    assert source.index("observed.version_id != content.version_id") < source.index(
        "register_source_version_observation("
    )


def test_new_authenticated_proposal_calls_the_exact_producer_observer() -> None:
    source = inspect.getsource(ApplicationService._entities_proposals_create)
    assert "self._proposal_origin(authorization)" in source
    assert "if self._relationship_reenrichment_enabled and admission.created:" in source
    assert "register_producer_version_observation(" in source
    assert "proposal_version=admission.state.value" in source
    assert 'proposal_version="1"' not in source
    assert source.index("self._proposal_origin(authorization)") < source.index(
        "register_producer_version_observation("
    )


def test_old_proxy_callers_do_not_register_reenrichment() -> None:
    enrollment = inspect.getsource(ApplicationService._sources_enroll)
    observation = inspect.getsource(ApplicationService._entities_observe)
    assert "reenrichment_cause_id" not in enrollment
    assert "SOURCE_VERSION_CHANGE" not in observation


def test_every_direct_specialized_caller_is_excluded_from_generic_registration() -> None:
    assert frozenset(_DIRECT_CALLERS) == _DIRECT_REENRICHMENT_CAPABILITIES
    assert set(_DIRECT_REENRICHMENT_CAPABILITIES).isdisjoint(TRIGGERS_BY_MUTATION_CAPABILITY)
    for handler_name, trigger in _DIRECT_CALLERS.values():
        source = inspect.getsource(getattr(ApplicationService, handler_name))
        assert "self._register_reenrichment(" in source
        assert f"ReenrichmentTrigger.{trigger.name}" in source


def test_direct_generic_and_version_observers_cover_all_nine_trigger_families() -> None:
    reached = {
        trigger for triggers in TRIGGERS_BY_MUTATION_CAPABILITY.values() for trigger in triggers
    }
    reached.update(trigger for _handler_name, trigger in _DIRECT_CALLERS.values())
    reached.update(
        {
            ReenrichmentTrigger.SOURCE_VERSION_CHANGE,
            ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE,
        }
    )
    assert reached == set(ReenrichmentTrigger)
