"""KLP-WP-04: the DOMAIN_OWNED routing table of autonomous submit (FAST).

KLP-AC-097 and KLP-AC-128 (contract half; the database half is
`tests/database/test_knowledge_domain_owned_routing.py`). Unmarked, routed to
repository-checks / validate and dependency-floor.

`decide_domain_route` is the pure decision `_AutonomousSubmit` applies at C2
from the immutable predicate head (R6 sections 8.5 and 13), over the eight
frozen seeds:

* `project.decision` -> `domain_owned_no_intake` naming `continuity_decision`;
* `project.critical_date` + a resolving owner ref -> `domain_owned_routed` to
  tasks / commitments / constraints / meetings with `routed_record_id` = the
  ref; an unresolvable ref -> refused `owner_ref_invalid`; no ref -> the
  Knowledge plane (`None`: Review decides);
* `entity.communication_preference` -> `domain_owned_no_intake` naming
  `relationship_memory` (KLP-WP-04 deviation: no Knowledge citation is a
  transferable Relationship Memory proposal citation);
* an owner ref on any other predicate -> refused `owner_ref_invalid`;
* every other (Knowledge-owned) seed without a ref -> `None`;
* every routed outcome satisfies the stored-result CHECK shape of section 11
  (owner set and not `knowledge_assertion`; routed id only when routed).
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.unit.test_knowledge_assertion_domain import SEEDS, _predicate_from_seed

from my_pa.domain.knowledge_assertion.admission import (
    OWNER_REF_ROUTES,
    DomainRoute,
    decide_domain_route,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeCanonicalOwner,
    KnowledgeOwnerRefKind,
    KnowledgeSubmissionOutcome,
    KnowledgeSubmissionReason,
)

CRITICAL: Final = "project.critical_date"
OWNER_IDS: Final = {
    KnowledgeOwnerRefKind.TASK: "tsk_synthetic00000001",
    KnowledgeOwnerRefKind.COMMITMENT: "cmt_synthetic00000001",
    KnowledgeOwnerRefKind.CONSTRAINT: "cst_synthetic00000001",
    KnowledgeOwnerRefKind.MEETING: "mtg_synthetic00000001",
}


def _route(
    code: str, kind: KnowledgeOwnerRefKind | None = None, *, resolves: bool = False
) -> DomainRoute | None:
    return decide_domain_route(
        _predicate_from_seed(SEEDS[code]),
        owner_ref_kind=kind,
        owner_ref_id=None if kind is None else OWNER_IDS[kind],
        owner_ref_resolves=resolves,
    )


def test_project_decision_is_no_intake_naming_continuity_decision() -> None:
    assert _route("project.decision") == DomainRoute(
        outcome=KnowledgeSubmissionOutcome.DOMAIN_OWNED_NO_INTAKE,
        reason=KnowledgeSubmissionReason.CANONICAL_OWNER_NO_INTAKE,
        canonical_owner=KnowledgeCanonicalOwner.CONTINUITY_DECISION,
    )


@pytest.mark.parametrize("kind", list(KnowledgeOwnerRefKind), ids=lambda k: k.value)
def test_a_resolving_owner_ref_routes_a_critical_date_to_its_owner(
    kind: KnowledgeOwnerRefKind,
) -> None:
    assert _route(CRITICAL, kind, resolves=True) == DomainRoute(
        outcome=KnowledgeSubmissionOutcome.DOMAIN_OWNED_ROUTED,
        reason=KnowledgeSubmissionReason.CANONICAL_OWNER,
        canonical_owner=OWNER_REF_ROUTES[kind],
        routed_record_id=OWNER_IDS[kind],
    )


def test_the_owner_map_is_exactly_the_four_section_13_owners() -> None:
    assert {kind.value: owner.value for kind, owner in OWNER_REF_ROUTES.items()} == {
        "task": "tasks",
        "commitment": "commitments",
        "constraint": "constraints",
        "meeting": "meetings",
    }


@pytest.mark.parametrize("kind", list(KnowledgeOwnerRefKind), ids=lambda k: k.value)
def test_an_unresolvable_owner_ref_is_refused(kind: KnowledgeOwnerRefKind) -> None:
    route = _route(CRITICAL, kind, resolves=False)
    assert route is not None
    assert route.outcome is KnowledgeSubmissionOutcome.REFUSED
    assert route.reason is KnowledgeSubmissionReason.OWNER_REF_INVALID
    assert route.canonical_owner is None


def test_a_critical_date_without_an_owner_ref_stays_with_knowledge() -> None:
    assert _route(CRITICAL) is None


def test_communication_preference_is_no_intake_naming_relationship_memory() -> None:
    route = _route("entity.communication_preference")
    assert route is not None
    assert route.outcome is KnowledgeSubmissionOutcome.DOMAIN_OWNED_NO_INTAKE
    assert route.canonical_owner is KnowledgeCanonicalOwner.RELATIONSHIP_MEMORY


@pytest.mark.parametrize("code", sorted(set(SEEDS) - {CRITICAL}))
def test_an_owner_ref_elsewhere_is_refused_even_when_it_resolves(code: str) -> None:
    route = _route(code, KnowledgeOwnerRefKind.TASK, resolves=True)
    assert route is not None
    assert route.reason is KnowledgeSubmissionReason.OWNER_REF_INVALID


@pytest.mark.parametrize("code", sorted(SEEDS))
def test_every_seed_routes_by_its_frozen_owner(code: str) -> None:
    route = _route(code)
    owner = KnowledgeCanonicalOwner(SEEDS[code]["canonical_owner"])
    if owner is KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION:
        assert route is None
    else:
        assert route is not None
        assert route.canonical_owner is owner
        assert route.canonical_owner is not KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION
        assert route.routed_record_id is None
