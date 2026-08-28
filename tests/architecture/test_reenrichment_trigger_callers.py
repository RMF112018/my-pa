"""Exact RI re-enrichment observers are load-bearing production hooks."""

from __future__ import annotations

import inspect

from my_pa.application.entity_reenrichment import TRIGGERS_BY_MUTATION_CAPABILITY
from my_pa.application.service import ApplicationService


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
