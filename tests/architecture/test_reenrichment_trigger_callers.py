"""Exact RI re-enrichment observers are load-bearing production hooks."""

from __future__ import annotations

import inspect

from my_pa.application.entity_reenrichment import (
    TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND,
    TRIGGERS_BY_MUTATION_CAPABILITY,
    ReenrichmentTrigger,
    reenrichment_trigger_for_review_decision,
)
from my_pa.application.service import _DIRECT_REENRICHMENT_CAPABILITIES, ApplicationService

#: Production source a capability's trigger decision may be spelled in, beyond
#: the handler itself.
#:
#: `review.decide` is the one capability whose trigger is not a single literal
#: in its handler. WP-04 / RI-P3-HIGH-001 moved the decision out of
#: `_review_decide` and into the pure, total
#: `reenrichment_trigger_for_review_decision`, because the handler registered
#: `CONTRADICTION_RESOLUTION` for every committed decision -- all eight
#: dispositions and all four review subject kinds -- and a literal in a handler
#: cannot express "only an accepted `resolve_mention`". The assertion below
#: therefore searches the handler *and* the predicate it delegates to, which
#: keeps the property this test has always enforced (the trigger is named in
#: production source, reachable from the capability, never only in a test)
#: while following the code that now carries it. The behavioural precision the
#: move bought is proved exhaustively -- seventeen proposal kinds by eight
#: dispositions -- in `tests/unit/test_entity_reenrichment.py`.
_DELEGATED_TRIGGER_SOURCE = {
    "review.decide": reenrichment_trigger_for_review_decision,
}

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
    for capability, (handler_name, trigger) in _DIRECT_CALLERS.items():
        handler_source = inspect.getsource(getattr(ApplicationService, handler_name))
        assert "self._register_reenrichment(" in handler_source
        delegate = _DELEGATED_TRIGGER_SOURCE.get(capability)
        if delegate is None:
            assert f"ReenrichmentTrigger.{trigger.name}" in handler_source
        else:
            # The handler delegates the decision, and the literal lives in the
            # delegate's module-level closed table rather than in either
            # function body -- `inspect.getsource` of a function cannot see it.
            # Assert the two facts that actually matter instead, which is
            # stronger than the substring it replaces: the handler really calls
            # the delegate, and the delegate's closed table really *produces*
            # this trigger. A comment naming the trigger would satisfy a
            # substring search; it cannot satisfy either of these.
            assert f"{delegate.__name__}(" in handler_source
            assert trigger in set(TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND.values())


def test_the_review_decision_trigger_is_decided_by_the_closed_accepted_kind_map() -> None:
    """The `review.decide` delegate is exhaustive, closed, and not a stub.

    Replaces nothing: it is the extra assertion the union above buys back. A
    predicate that had quietly gone back to answering `CONTRADICTION_RESOLUTION`
    for everything would satisfy the source search and fail here.
    """
    assert set(TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND.values()) == {
        ReenrichmentTrigger.CONTRADICTION_RESOLUTION,
        ReenrichmentTrigger.NEW_ALIAS,
        ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
        ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    }
    contradiction = {
        kind
        for kind, trigger in TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND.items()
        if trigger is ReenrichmentTrigger.CONTRADICTION_RESOLUTION
    }
    assert {kind.value for kind in contradiction} == {"resolve_mention"}


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
