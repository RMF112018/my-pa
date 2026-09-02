"""Policy defaults to deny."""

from __future__ import annotations

import itertools

import pytest

from my_pa.domain.common.classification import Classification
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import (
    POLICY_VERSION,
    DenialReason,
    PolicyDecision,
    PolicyRequest,
    evaluate,
    validate_policy_version,
)

OPERATOR = Principal(
    principal_id="prn_operator0001", kind=PrincipalKind.OPERATOR, authenticated=True
)
GATEWAY = Principal(principal_id="prn_gateway00001", kind=PrincipalKind.GATEWAY, authenticated=True)
SOURCE = "src_abc123def456"


def _request(**overrides: object) -> PolicyRequest:
    base: dict[str, object] = {
        "principal": GATEWAY,
        "purpose": Purpose.KNOWLEDGE_SEARCH,
        "capability": Capability.KNOWLEDGE_SEARCH,
        "requested_source_ids": frozenset({SOURCE}),
        "authorized_source_ids": frozenset({SOURCE}),
    }
    base.update(overrides)
    return PolicyRequest(**base)  # type: ignore[arg-type]


def test_the_baseline_request_is_allowed() -> None:
    # Without this, every deny assertion below would pass vacuously.
    decision = evaluate(_request())
    assert decision.allowed
    assert decision.reason is None
    assert decision.policy_version == POLICY_VERSION


def test_unauthenticated_principal_is_denied() -> None:
    principal = Principal(principal_id="prn_gateway00001", kind=PrincipalKind.GATEWAY)
    decision = evaluate(_request(principal=principal))
    assert not decision.allowed
    assert decision.reason is DenialReason.PRINCIPAL_NOT_AUTHENTICATED


def test_principal_defaults_to_unauthenticated() -> None:
    principal = Principal(principal_id="prn_gateway00001", kind=PrincipalKind.GATEWAY)
    assert principal.authenticated is False


@pytest.mark.parametrize(
    "kind", [PrincipalKind.LOCAL_MODEL_GATEWAY, PrincipalKind.CLOUD_MODEL_PROVIDER]
)
def test_model_principals_cannot_hold_authority(kind: PrincipalKind) -> None:
    principal = Principal(principal_id="prn_model0000001", kind=kind, authenticated=True)
    decision = evaluate(_request(principal=principal))
    assert not decision.allowed
    assert decision.reason is DenialReason.PRINCIPAL_MAY_NOT_HOLD_AUTHORITY


def test_operator_only_capability_denies_non_operator() -> None:
    decision = evaluate(
        _request(capability=Capability.SOURCES_ENROLL, purpose=Purpose.BOUNDED_ENROLLMENT)
    )
    assert not decision.allowed
    assert decision.reason is DenialReason.OPERATOR_REQUIRED


def test_operator_only_capability_allows_operator() -> None:
    decision = evaluate(
        _request(
            principal=OPERATOR,
            capability=Capability.SOURCES_ENROLL,
            purpose=Purpose.BOUNDED_ENROLLMENT,
        )
    )
    assert decision.allowed


def test_empty_scope_is_not_a_wildcard() -> None:
    decision = evaluate(_request(requested_source_ids=frozenset()))
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_scope_outside_enrollment_is_denied() -> None:
    decision = evaluate(_request(requested_source_ids=frozenset({"src_zzz999zzz999"})))
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_partially_authorized_scope_is_denied() -> None:
    decision = evaluate(_request(requested_source_ids=frozenset({SOURCE, "src_zzz999zzz999"})))
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_enrollment_grants_scope_rather_than_requiring_it() -> None:
    """Enrollment is the operation that creates authorization.

    Requiring the scope to be held already would mean an operator could only
    enroll a source they had already enrolled, making the capability unusable.
    """
    decision = evaluate(
        _request(
            principal=OPERATOR,
            capability=Capability.SOURCES_ENROLL,
            purpose=Purpose.BOUNDED_ENROLLMENT,
            requested_source_ids=frozenset({"src_neverseen0001"}),
            authorized_source_ids=frozenset(),
        )
    )
    assert decision.allowed


def test_enrollment_still_requires_a_named_scope() -> None:
    decision = evaluate(
        _request(
            principal=OPERATOR,
            capability=Capability.SOURCES_ENROLL,
            purpose=Purpose.BOUNDED_ENROLLMENT,
            requested_source_ids=frozenset(),
            authorized_source_ids=frozenset(),
        )
    )
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_enrollment_relaxation_does_not_leak_to_read_capabilities() -> None:
    # The relaxation above must apply to sources.enroll and nothing else.
    for capability in Capability:
        if capability in (Capability.SOURCES_ENROLL, Capability.CAPABILITIES_GET):
            continue
        principal = OPERATOR if is_operator_only(capability) else GATEWAY
        for purpose in permitted_purposes(capability):
            decision = evaluate(
                _request(
                    principal=principal,
                    capability=capability,
                    purpose=purpose,
                    requested_source_ids=frozenset({"src_neverseen0001"}),
                    authorized_source_ids=frozenset(),
                )
            )
            assert not decision.allowed, f"{capability}/{purpose} allowed an unheld scope"
            assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_capabilities_get_carries_no_source_scope() -> None:
    allowed = evaluate(
        _request(
            capability=Capability.CAPABILITIES_GET,
            purpose=Purpose.STATUS_OBSERVATION,
            requested_source_ids=frozenset(),
            authorized_source_ids=frozenset(),
        )
    )
    assert allowed.allowed
    denied = evaluate(
        _request(capability=Capability.CAPABILITIES_GET, purpose=Purpose.STATUS_OBSERVATION)
    )
    assert not denied.allowed
    assert denied.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_private_content_is_never_cloud_eligible() -> None:
    for classification in (Classification.PRIVATE_LOCAL, Classification.RESTRICTED_LOCAL):
        decision = evaluate(_request(to_cloud=True, classification=classification))
        assert not decision.allowed
        assert decision.reason is DenialReason.DESTINATION_NOT_ELIGIBLE


def test_synthetic_test_data_may_leave_the_boundary() -> None:
    decision = evaluate(_request(to_cloud=True, classification=Classification.SYNTHETIC_TEST))
    assert decision.allowed


#: Capability/purpose pairs the contract permits, written out rather than read
#: from `permitted_purposes`. Deriving the mismatch set from the function under
#: test made the suite vacuous under exactly the mutation it existed to catch:
#: opening every purpose emptied the parameter list and the test still passed.
PERMITTED_PAIRS: frozenset[tuple[Capability, Purpose]] = frozenset(
    {
        (Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION),
        (Capability.CAPABILITIES_GET, Purpose.SECURITY_VALIDATION),
        (Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION),
        (Capability.SOURCES_METADATA, Purpose.SOURCE_INSPECTION),
        (Capability.SOURCES_FETCH, Purpose.SOURCE_INSPECTION),
        (Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION),
        (Capability.SOURCES_STATUS, Purpose.STATUS_OBSERVATION),
        (Capability.SOURCES_ENROLL, Purpose.BOUNDED_ENROLLMENT),
        (Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH),
        (Capability.KNOWLEDGE_READ, Purpose.KNOWLEDGE_READ),
        (Capability.KNOWLEDGE_REVEAL, Purpose.CAPTURE_REVIEW),
        (Capability.CAPTURE_CREATE, Purpose.CAPTURE_AUTHORING),
        (Capability.CAPTURE_REVISE, Purpose.CAPTURE_AUTHORING),
        (Capability.CAPTURE_READ, Purpose.CAPTURE_REVIEW),
        (Capability.CAPTURE_LIST, Purpose.CAPTURE_REVIEW),
        (Capability.CAPTURE_SEARCH, Purpose.CAPTURE_REVIEW),
        (Capability.REVIEW_LIST, Purpose.CAPTURE_REVIEW),
        (Capability.REVIEW_DECIDE, Purpose.REVIEW_DISPOSITION),
        (Capability.CONTINUITY_PULSE, Purpose.CAPTURE_REVIEW),
        (Capability.CONTINUITY_SITUATIONS, Purpose.CAPTURE_REVIEW),
        (Capability.CONTINUITY_PROJECTS, Purpose.CAPTURE_REVIEW),
        (Capability.CONTINUITY_PROJECTS_CREATE, Purpose.CONTINUITY_AUTHORING),
        (Capability.CONTINUITY_SITUATIONS_CREATE, Purpose.CONTINUITY_AUTHORING),
        (Capability.CONTINUITY_TASKS_CREATE, Purpose.CONTINUITY_AUTHORING),
        (Capability.KNOWLEDGE_COVERAGE, Purpose.STATUS_OBSERVATION),
        # WP-28's managed-document plane. A purpose pair of its own rather than
        # a reuse of the capture or knowledge pair, and the writes and the reads
        # are separated: a purpose wide enough to cover both would grant both.
        (Capability.DOCUMENTS_CREATE, Purpose.DOCUMENT_AUTHORING),
        (Capability.DOCUMENTS_REVISE, Purpose.DOCUMENT_AUTHORING),
        (Capability.DOCUMENTS_ARCHIVE, Purpose.DOCUMENT_AUTHORING),
        (Capability.DOCUMENTS_RESTORE, Purpose.DOCUMENT_AUTHORING),
        (Capability.DOCUMENTS_READ, Purpose.DOCUMENT_READ),
        (Capability.DOCUMENTS_LIST, Purpose.DOCUMENT_READ),
        # WP-TM-03's task-read plane. All four capabilities share the single
        # `task_read` purpose, exactly as the capture-plane reads share
        # `capture_review` and the knowledge-plane reads share `knowledge_read`.
        (Capability.TASKS_READ, Purpose.TASK_READ),
        (Capability.TASKS_LIST, Purpose.TASK_READ),
        (Capability.TASKS_SEARCH, Purpose.TASK_READ),
        (Capability.TASKS_HISTORY, Purpose.TASK_READ),
        # WP-TM-04's task-write plane. All five capabilities share the single
        # `task_authoring` purpose, exactly as the managed-document writes share
        # `document_authoring` and the capture writes share `capture_authoring`.
        # A purpose wide enough to cover writing and reading is a purpose that
        # grants both, so the write purpose is separate from the read purpose.
        (Capability.TASKS_CREATE, Purpose.TASK_AUTHORING),
        (Capability.TASKS_UPDATE, Purpose.TASK_AUTHORING),
        (Capability.TASKS_TRANSITION, Purpose.TASK_AUTHORING),
        (Capability.TASKS_BULK_PREVIEW, Purpose.TASK_AUTHORING),
        (Capability.TASKS_BULK_CONFIRM, Purpose.TASK_AUTHORING),
        # WP-TM-05's commitment plane. Three reads share `commitment_read`,
        # two writes share `commitment_authoring`, exactly paralleling the
        # task plane's read/authoring split.
        (Capability.COMMITMENTS_READ, Purpose.COMMITMENT_READ),
        (Capability.COMMITMENTS_LIST, Purpose.COMMITMENT_READ),
        (Capability.COMMITMENTS_SEARCH, Purpose.COMMITMENT_READ),
        (Capability.COMMITMENTS_HISTORY, Purpose.COMMITMENT_READ),
        (Capability.COMMITMENTS_WAITING_ON, Purpose.COMMITMENT_READ),
        (Capability.COMMITMENTS_CREATE, Purpose.COMMITMENT_AUTHORING),
        (Capability.COMMITMENTS_UPDATE, Purpose.COMMITMENT_AUTHORING),
        (Capability.COMMITMENTS_CLOSE, Purpose.COMMITMENT_AUTHORING),
        (Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION),
        (Capability.CONTEXT_FEEDBACK, Purpose.CONTEXT_PREFERENCE),
        (Capability.GOODNOTES_WORK, Purpose.GOODNOTES_WORK),
        (Capability.GOODNOTES_CONTENT, Purpose.GOODNOTES_CONTENT),
        (Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL),
        (Capability.GSQS_START, Purpose.GSQS_B0_EXECUTION),
        (Capability.GSQS_STATUS, Purpose.GSQS_B0_OBSERVATION),
        (Capability.REPORTS_BEGIN_CYCLE, Purpose.REPORT_AUTHORING),
        (Capability.REPORTS_COMMIT, Purpose.REPORT_AUTHORING),
        (Capability.REPORTS_RECORD_RUN_STATE, Purpose.REPORT_AUTHORING),
        (Capability.REPORTS_READ, Purpose.REPORT_READ),
        (Capability.REPORTS_LATEST, Purpose.REPORT_READ),
        (Capability.REPORTS_LIST, Purpose.REPORT_READ),
        (Capability.REPORTS_SEARCH, Purpose.REPORT_READ),
        (Capability.REPORTS_RESOLVE_SET, Purpose.REPORT_READ),
        # The entity plane. Every read on it shares the single `entity_read`
        # purpose, exactly as the task-plane reads share `task_read`. The writes
        # take `entity_authoring`, except `entities.observe`, which takes
        # `entity_observation_ingest` and nothing else -- separated rather than
        # merged, on the rule the capture and managed-document planes each
        # carry: a purpose wide enough to cover writing and reading is a purpose
        # that grants both, and one wide enough to cover recording evidence and
        # deciding an identity is a purpose that grants both of those.
        (Capability.ENTITIES_SEARCH, Purpose.ENTITY_READ),
        (Capability.ENTITIES_GET, Purpose.ENTITY_READ),
        (Capability.ENTITIES_RESOLVE, Purpose.ENTITY_READ),
        (Capability.ENTITIES_CONTEXT, Purpose.ENTITY_READ),
        (Capability.ENTITIES_RELATIONSHIPS, Purpose.ENTITY_READ),
        (Capability.ENTITIES_UNRESOLVED_MENTIONS, Purpose.ENTITY_READ),
        (Capability.ENTITIES_IDENTIFIERS_LIST, Purpose.ENTITY_READ),
        (Capability.ENTITIES_ALIASES_LIST, Purpose.ENTITY_READ),
        # The plane's writes take `entity_authoring` (`WP-RI-A-02`), and the
        # split is the one every plane here makes between reading and writing:
        # a grant issued so an assistant can look up who someone is must not
        # also let it rename them or retire the address their mail arrives at.
        (Capability.ENTITIES_CREATE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_UPDATE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_ARCHIVE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_RESTORE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_IDENTIFIERS_BIND, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_IDENTIFIERS_RETIRE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_IDENTIFIERS_SUPERSEDE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_ALIASES_ADD, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_ALIASES_RETIRE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_ALIASES_SUPERSEDE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_ASSIGNMENTS_LIST, Purpose.ENTITY_READ),
        (Capability.ENTITIES_ASSIGNMENTS_CREATE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_ASSIGNMENTS_REVISE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_ASSIGNMENTS_END, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_RELATIONSHIPS_CREATE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_RELATIONSHIPS_REVISE, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_RELATIONSHIPS_END, Purpose.ENTITY_AUTHORING),
        (Capability.ENTITIES_OBSERVATIONS_LIST, Purpose.ENTITY_READ),
        (Capability.ENTITIES_OBSERVE, Purpose.ENTITY_OBSERVATION_INGEST),
        (Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE, Purpose.ENTITY_AUTHORING),
        (Capability.RELATIONSHIP_MEMORY_CREATE, Purpose.RELATIONSHIP_MEMORY_AUTHORING),
        (Capability.RELATIONSHIP_MEMORY_REVISE, Purpose.RELATIONSHIP_MEMORY_AUTHORING),
        (Capability.RELATIONSHIP_MEMORY_ARCHIVE, Purpose.RELATIONSHIP_MEMORY_AUTHORING),
        (Capability.RELATIONSHIP_MEMORY_RESTORE, Purpose.RELATIONSHIP_MEMORY_AUTHORING),
        # Phase B's four, one purpose each. The two producer paths carry purposes
        # neither plane's existing pair holds, which is what keeps a client that
        # may raise candidates from thereby authoring what it proposed; the two
        # identity-correction halves share one purpose, which is the coupling
        # `purpose.py` argues for rather than works around.
        (Capability.ENTITIES_PROPOSALS_CREATE, Purpose.ENTITY_PROPOSAL),
        (Capability.RELATIONSHIP_MEMORY_PROPOSE, Purpose.RELATIONSHIP_MEMORY_PROPOSAL),
        (Capability.ENTITIES_MERGE_PREVIEW, Purpose.ENTITY_IDENTITY_CORRECTION),
        (Capability.ENTITIES_MERGE, Purpose.ENTITY_IDENTITY_CORRECTION),
        (Capability.ENTITIES_IDENTITY_HISTORY, Purpose.ENTITY_READ),
        (Capability.ENTITIES_SPLIT_PREVIEW, Purpose.ENTITY_IDENTITY_CORRECTION),
        (Capability.ENTITIES_SPLIT, Purpose.ENTITY_IDENTITY_CORRECTION),
        (Capability.RELATIONSHIP_MEMORY_GET, Purpose.RELATIONSHIP_MEMORY_READ),
        (Capability.RELATIONSHIP_MEMORY_LIST, Purpose.RELATIONSHIP_MEMORY_READ),
        (Capability.RELATIONSHIP_MEMORY_SEARCH, Purpose.RELATIONSHIP_MEMORY_READ),
        (Capability.RELATIONSHIP_MEMORY_HISTORY, Purpose.RELATIONSHIP_MEMORY_READ),
        # `RI-ENT-WP-10`'s five record-family reads, all under the read purpose
        # the plane's other reads already hold and none under a write purpose.
        (Capability.ENTITIES_PROFILE, Purpose.ENTITY_READ),
        (Capability.ENTITIES_NAMES_LIST, Purpose.ENTITY_READ),
        (Capability.ENTITIES_ADDRESSES_LIST, Purpose.ENTITY_READ),
        (Capability.ENTITIES_COMMUNICATION_LIST, Purpose.ENTITY_READ),
        (Capability.ENTITIES_PARTICIPATIONS_LIST, Purpose.ENTITY_READ),
    }
)

MISMATCHED_PAIRS = sorted(
    set(itertools.product(Capability, Purpose)) - PERMITTED_PAIRS,
    key=lambda pair: (pair[0].value, pair[1].value),
)


def test_the_permitted_pair_table_matches_the_implementation() -> None:
    derived = {
        (capability, purpose)
        for capability in Capability
        for purpose in permitted_purposes(capability)
    }
    assert derived == PERMITTED_PAIRS


def test_the_mismatch_parametrisation_is_not_empty() -> None:
    # Pins the parameter count, so widening permitted_purposes cannot silently
    # empty the table below. The three numbers are written out rather than
    # derived from each other: the arithmetic is what makes the second a check on
    # the enums, and the literals are what make it a check on the arithmetic.
    # WP-TM-03 added 4 capabilities and 1 purpose; WP-TM-04 added 5 and 1;
    # WP-TM-05 added 5 and 2; context.prepare/feedback added 2 capabilities and
    # 2 purposes; goodnotes.work/propose added 2 capabilities and 2 purposes;
    # goodnotes.content added 1 capability and 1 purpose; the entity plane added
    # 5 capabilities and 1 purpose, and its unresolved-mention queue one
    # more capability under the purpose the other five already use; the
    # Intelligence Artifact plane added 8 capabilities and 2 purposes; WP-FE-03
    # added 3 commitment capabilities and no purpose, two reads under
    # `commitment_read` and one write under `commitment_authoring`, so it
    # contributes three pairs; the Relationship Memory plane added 8
    # capabilities and 2 purposes, and it maps one-to-one onto them — four
    # writes under `relationship_memory_authoring` and four reads under
    # `relationship_memory_read` — so it contributes eight pairs rather than the
    # sixteen a cross product would give; Phase A added 22 `entities.`
    # capabilities and 2 purposes, and maps each capability onto exactly one of
    # the three the plane now has -- four paged reads under the `entity_read`
    # the earlier reads already use, `entities.observe` under
    # `entity_observation_ingest` and nothing else, and the other seventeen
    # writes under `entity_authoring` -- so it contributes twenty-two pairs
    # rather than the sixty-six a cross product would give.
    # Phase B added both producer paths and the governed merge pair, with one
    # purpose per producer and one shared by preview/apply -- so it contributes
    # four pairs rather than the twelve a cross product would give.
    # Final identity recovery adds one read and the operator-only split
    # preview/apply pair. GSQS B0 adds its start/status pairs. `RI-ENT-WP-10`
    # adds five `entities.` reads and no purpose, each under the `entity_read`
    # the plane's other reads already use, so it contributes five pairs.
    # Unioned: 109 capabilities, 34 purposes, 111 permitted pairs.
    assert len(PERMITTED_PAIRS) == 111
    assert len(MISMATCHED_PAIRS) == len(Capability) * len(Purpose) - 111 == 3595


@pytest.mark.parametrize(("capability", "purpose"), MISMATCHED_PAIRS)
def test_every_mismatched_purpose_is_denied(capability: Capability, purpose: Purpose) -> None:
    principal = OPERATOR if is_operator_only(capability) else GATEWAY
    decision = evaluate(_request(principal=principal, capability=capability, purpose=purpose))
    assert not decision.allowed
    assert decision.reason is DenialReason.PURPOSE_NOT_PERMITTED_FOR_CAPABILITY


def test_principal_validates_its_identifier() -> None:
    for bad in ("/Users/someone", "prn_bad", "src_abc123def456", "prn_host.example.com"):
        with pytest.raises(ValueError, match="identifier"):
            Principal(principal_id=bad, kind=PrincipalKind.OPERATOR, authenticated=True)


def test_is_operator_requires_authentication() -> None:
    """`evaluate` only survives an unauthenticated operator by short-circuiting.

    Without this, dropping the `authenticated` conjunct from `is_operator` would
    make an unauthenticated operator report True with no test failing, leaving
    the property unsafe for any future caller that checks it directly.
    """
    unauthenticated = Principal(principal_id="prn_operator0001", kind=PrincipalKind.OPERATOR)
    assert unauthenticated.is_operator is False
    assert unauthenticated.may_hold_authority is False
    assert OPERATOR.is_operator is True


def test_every_capability_has_at_least_one_permitted_purpose() -> None:
    for capability in Capability:
        assert permitted_purposes(capability), f"{capability} would be permanently denied"


def test_goodnotes_capabilities_are_not_operator_only() -> None:
    assert not is_operator_only(Capability.GOODNOTES_WORK)
    assert not is_operator_only(Capability.GOODNOTES_CONTENT)
    assert not is_operator_only(Capability.GOODNOTES_PROPOSE)


def test_decision_cannot_be_allowed_with_a_reason() -> None:
    with pytest.raises(ValueError, match="cannot carry a denial reason"):
        PolicyDecision(
            allowed=True,
            policy_version=POLICY_VERSION,
            reason=DenialReason.SCOPE_NOT_AUTHORIZED,
        )


def test_denial_must_carry_a_reason() -> None:
    with pytest.raises(ValueError, match="must carry a reason"):
        PolicyDecision(allowed=False, policy_version=POLICY_VERSION)


def test_decision_validates_its_own_policy_version() -> None:
    """Pinned independently of AuditEvent.

    AuditEvent revalidates, so it provides defence in depth — which means a
    refactor could delete this check and every other test would still pass.
    """
    for bad in ("postgres://user:pw@host/db", "policy-vX", "v1", "", "policy-v1; DROP TABLE"):
        with pytest.raises(ValueError, match="policy version"):
            PolicyDecision(allowed=True, policy_version=bad)


def test_decision_rejects_a_non_string_policy_version() -> None:
    with pytest.raises(ValueError, match="must be a string"):
        PolicyDecision(allowed=True, policy_version=123)  # type: ignore[arg-type]


def test_evaluate_emits_a_well_formed_policy_version() -> None:
    assert validate_policy_version(evaluate(_request()).policy_version) == POLICY_VERSION
