"""Durable RI re-enrichment bindings and pre-application currency gate."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.entity_reenrichment import (
    MAX_REENRICHMENT_VERSIONS,
    TRIGGERS_BY_MUTATION_CAPABILITY,
    BindingCurrency,
    BindingVersion,
    CurrentReenrichmentBindings,
    EntityReenrichmentService,
    ProductionReenrichmentCaller,
    ReenrichmentBinding,
    ReenrichmentLimitation,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
    ReenrichmentWork,
    StaleBindingReason,
    assess_currency,
    reenrichment_trigger_for_review_decision,
    register_mutation_reenrichment,
    register_producer_version_observation,
    register_source_version_observation,
)
from my_pa.application.service import _register_reenrichment_result, _Result
from my_pa.contracts.ports import ReenrichmentVersionObservation
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import Disposition
from my_pa.domain.relationship.proposal_payload import EntityProposalKind

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY = "ent_aaaa0001aaaa0001"
ALIAS = "eals_aaaa0001aaaa0001"
SOURCE_OBJECT = "obj_aaaa0001aaaa0001"
SOURCE_VERSION = "ver_aaaa0001aaaa0001"
PROPOSAL = "eprp_aaaa0001aaaa0001"
WHEN = datetime(2026, 8, 28, 12, tzinfo=UTC)

_DIRECT_SPECIALIZED_TRIGGERS = frozenset(
    {
        ReenrichmentTrigger.CORRECTED_IDENTITY,
        ReenrichmentTrigger.NEW_ALIAS,
        ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
        ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
        ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION,
        ReenrichmentTrigger.CONTRADICTION_RESOLUTION,
    }
)
_VERSION_OBSERVER_TRIGGERS = frozenset(
    {
        ReenrichmentTrigger.SOURCE_VERSION_CHANGE,
        ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE,
    }
)


@dataclass(frozen=True)
class _Observation:
    changed: bool


def _binding(**changes: object) -> ReenrichmentBinding:
    values: dict[str, object] = {
        "principal_id": PRINCIPAL,
        "trigger": ReenrichmentTrigger.NEW_ALIAS,
        "cause_record_id": "emut_aaaa0001aaaa0001",
        "subjects": (
            ReenrichmentSubject(ReenrichmentSubjectKind.ENTITY, ENTITY, "7"),
            ReenrichmentSubject(ReenrichmentSubjectKind.ALIAS, ALIAS, "1"),
        ),
        "input_versions": (BindingVersion("resolution_rules", "rules-v2"),),
        "producer_versions": (BindingVersion("deterministic_resolver", "resolver-v3"),),
        "policy_version": "policy-v1",
    }
    values.update(changes)
    return ReenrichmentBinding(**values)  # type: ignore[arg-type]


class _Current:
    def __init__(self, binding: ReenrichmentBinding) -> None:
        self.subjects = {(item.kind, item.subject_id): item.version for item in binding.subjects}
        self.inputs = {item.key: item.version for item in binding.input_versions}
        self.producers = {item.key: item.version for item in binding.producer_versions}
        self.policy = binding.policy_version

    def subject_version(
        self, principal_id: str, kind: ReenrichmentSubjectKind, subject_id: str
    ) -> str | None:
        return None if principal_id != PRINCIPAL else self.subjects.get((kind, subject_id))

    def input_version(self, principal_id: str, key: str) -> str | None:
        return None if principal_id != PRINCIPAL else self.inputs.get(key)

    def producer_version(self, principal_id: str, key: str) -> str | None:
        return None if principal_id != PRINCIPAL else self.producers.get(key)

    def policy_version(self, principal_id: str) -> str | None:
        return None if principal_id != PRINCIPAL else self.policy


class _Repository:
    def __init__(self) -> None:
        self.registered: dict[str, ReenrichmentWork] = {}
        self.by_id: dict[str, ReenrichmentWork] = {}
        self.stale: list[tuple[str, tuple[StaleBindingReason, ...]]] = []
        self.completed: list[str] = []
        self.live_claim = True
        self.versions: dict[tuple[str, str], str] = {}

    def register(self, binding: ReenrichmentBinding, *, at: datetime) -> ReenrichmentWork:
        prior = self.registered.get(binding.binding_sha256)
        if prior is not None:
            return prior
        work = ReenrichmentWork(
            work_id=f"erwk_{len(self.registered) + 1:08d}",
            binding=binding,
            state=ReenrichmentState.QUEUED,
            attempt_count=0,
            max_attempts=3,
            created_at=at,
            updated_at=at,
        )
        self.registered[binding.binding_sha256] = work
        self.by_id[work.work_id] = work
        return work

    def apply_claimed(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        current: CurrentReenrichmentBindings,
        apply: Callable[[ReenrichmentBinding, str], None],
        at: datetime,
    ) -> BindingCurrency:
        assert principal_id == PRINCIPAL and owner == "worker_01" and at == WHEN
        work = self.by_id.get(work_id, _claimed(_binding()))
        if not self.live_claim:
            raise ValueError("re-enrichment application requires this worker's live claim")
        currency = assess_currency(work.binding, current)
        if not currency.is_current:
            self.stale.append((work_id, currency.reasons))
            return currency
        apply(work.binding, work.binding.binding_sha256)
        self.completed.append(work_id)
        return currency

    def observe_version(
        self,
        principal_id: str,
        *,
        namespace: str,
        key: str,
        version: str,
        at: datetime,
    ) -> ReenrichmentVersionObservation:
        del principal_id, at
        previous = self.versions.get((namespace, key))
        self.versions[(namespace, key)] = version

        return _Observation(previous is not None and previous != version)


class _SqlEquivalentCurrent:
    """The application-visible semantics of SqlCurrentReenrichmentBindings."""

    def __init__(
        self,
        repository: _Repository,
        *,
        subjects: dict[tuple[ReenrichmentSubjectKind, str], str] | None = None,
    ) -> None:
        self.repository = repository
        self.subjects = subjects or {}

    def subject_version(
        self, principal_id: str, kind: ReenrichmentSubjectKind, subject_id: str
    ) -> str | None:
        if principal_id != PRINCIPAL:
            return None
        if kind is ReenrichmentSubjectKind.PRINCIPAL:
            return "1" if subject_id == principal_id else None
        return self.subjects.get((kind, subject_id))

    def input_version(self, principal_id: str, key: str) -> str | None:
        if principal_id != PRINCIPAL:
            return None
        return self.repository.versions.get(("input", key))

    def producer_version(self, principal_id: str, key: str) -> str | None:
        if principal_id != PRINCIPAL:
            return None
        return self.repository.versions.get(("producer", key))

    def policy_version(self, principal_id: str) -> str | None:
        if principal_id != PRINCIPAL:
            return None
        return self.repository.versions.get(("policy", "current"))


def _as_claimed(repository: _Repository, work: ReenrichmentWork) -> ReenrichmentWork:
    claimed = replace(
        work,
        state=ReenrichmentState.RUNNING,
        attempt_count=1,
        updated_at=WHEN,
        lease_owner="worker_01",
        lease_expires_at=WHEN + timedelta(minutes=1),
    )
    repository.by_id[work.work_id] = claimed
    return claimed


def _claimed(binding: ReenrichmentBinding) -> ReenrichmentWork:
    return ReenrichmentWork(
        work_id="erwk_aaaa0001aaaa0001",
        binding=binding,
        state=ReenrichmentState.RUNNING,
        attempt_count=1,
        max_attempts=3,
        created_at=WHEN - timedelta(minutes=1),
        updated_at=WHEN - timedelta(seconds=1),
        lease_owner="worker_01",
        lease_expires_at=WHEN + timedelta(minutes=1),
    )


def test_the_trigger_vocabulary_is_exactly_the_nine_governing_triggers() -> None:
    assert {item.value for item in ReenrichmentTrigger} == {
        "corrected_identity",
        "new_alias",
        "project_mapping_change",
        "role_or_organization_change",
        "source_version_change",
        "model_or_rule_version_change",
        "accepted_quick_capture_correction",
        "contradiction_resolution",
        "policy_change",
    }


def test_binding_digest_is_order_independent_and_version_sensitive() -> None:
    binding = _binding()
    reordered = _binding(
        subjects=tuple(reversed(binding.subjects)),
        input_versions=tuple(reversed(binding.input_versions)),
    )
    changed = replace(binding, input_versions=(BindingVersion("resolution_rules", "rules-v3"),))
    assert reordered.binding_sha256 == binding.binding_sha256
    assert changed.binding_sha256 != binding.binding_sha256


@pytest.mark.parametrize(
    "subjects",
    [
        (
            ReenrichmentSubject(ReenrichmentSubjectKind.ENTITY, ENTITY, "7"),
            ReenrichmentSubject(ReenrichmentSubjectKind.ENTITY, ENTITY, "8"),
        ),
        (
            ReenrichmentSubject(ReenrichmentSubjectKind.ENTITY, ENTITY, "7"),
            ReenrichmentSubject(ReenrichmentSubjectKind.ENTITY, ENTITY, "7"),
        ),
    ],
)
def test_duplicate_subject_identity_is_rejected(
    subjects: tuple[ReenrichmentSubject, ReenrichmentSubject],
) -> None:
    with pytest.raises(ValueError, match="subject identity once"):
        _binding(subjects=subjects)


@pytest.mark.parametrize(
    "versions",
    [
        (BindingVersion("resolver", "v1"), BindingVersion("resolver", "v2")),
        (BindingVersion("resolver", "v1"), BindingVersion("resolver", "v1")),
    ],
)
def test_duplicate_version_key_is_rejected(
    versions: tuple[BindingVersion, BindingVersion],
) -> None:
    with pytest.raises(ValueError, match="version key once"):
        _binding(input_versions=versions)


def test_an_identical_registration_dedupes_and_a_changed_version_does_not() -> None:
    repository = _Repository()
    service = EntityReenrichmentService(repository)
    first = service.register(_binding(), at=WHEN)
    replay = service.register(_binding(), at=WHEN)
    changed = service.register(
        _binding(policy_version="policy-v2", cause_record_id="audit_bbbb0002bbbb0002"),
        at=WHEN,
    )
    assert replay.work_id == first.work_id
    assert changed.work_id != first.work_id
    assert len(repository.registered) == 2


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("subject", StaleBindingReason.SUBJECT_VERSION_CHANGED),
        ("input", StaleBindingReason.INPUT_VERSION_CHANGED),
        ("producer", StaleBindingReason.PRODUCER_VERSION_CHANGED),
        ("policy", StaleBindingReason.POLICY_VERSION_CHANGED),
    ],
)
def test_every_version_class_can_make_work_stale(change: str, reason: StaleBindingReason) -> None:
    binding = _binding()
    current = _Current(binding)
    if change == "subject":
        current.subjects[(ReenrichmentSubjectKind.ENTITY, ENTITY)] = "8"
    elif change == "input":
        current.inputs["resolution_rules"] = "rules-v3"
    elif change == "producer":
        current.producers["deterministic_resolver"] = "resolver-v4"
    else:
        current.policy = "policy-v2"
    assert reason in assess_currency(binding, current).reasons


def test_stale_work_is_recorded_and_the_applier_is_never_called() -> None:
    binding = _binding()
    current = _Current(binding)
    current.policy = "policy-v2"
    repository = _Repository()
    applied: list[ReenrichmentBinding] = []
    currency = EntityReenrichmentService(repository).apply_claimed(
        _claimed(binding),
        owner="worker_01",
        current=current,
        apply=lambda held, _key: applied.append(held),
        at=WHEN,
    )
    assert currency.reasons == (StaleBindingReason.POLICY_VERSION_CHANGED,)
    assert applied == []
    assert repository.stale == [
        ("erwk_aaaa0001aaaa0001", (StaleBindingReason.POLICY_VERSION_CHANGED,))
    ]
    assert repository.completed == []


def test_current_work_applies_once_then_completes() -> None:
    binding = _binding()
    repository = _Repository()
    applied: list[str] = []
    currency = EntityReenrichmentService(repository).apply_claimed(
        _claimed(binding),
        owner="worker_01",
        current=_Current(binding),
        apply=lambda held, key: applied.append(key),
        at=WHEN,
    )
    assert currency.is_current
    assert applied == [binding.binding_sha256]
    assert repository.completed == ["erwk_aaaa0001aaaa0001"]


def test_expired_claim_never_invokes_the_applier() -> None:
    binding = _binding()
    repository = _Repository()
    repository.live_claim = False
    applied: list[ReenrichmentBinding] = []
    expired = replace(_claimed(binding), lease_expires_at=WHEN)

    with pytest.raises(ValueError, match="live claim"):
        EntityReenrichmentService(repository).apply_claimed(
            expired,
            owner="worker_01",
            current=_Current(binding),
            apply=lambda held, _key: applied.append(held),
            at=WHEN,
        )

    assert applied == []
    assert repository.stale == []
    assert repository.completed == []


def test_cross_principal_subject_binding_is_refused() -> None:
    with pytest.raises(ValueError, match="own Principal"):
        _binding(
            subjects=(
                ReenrichmentSubject(
                    ReenrichmentSubjectKind.PRINCIPAL, OTHER_PRINCIPAL, "policy-v1"
                ),
            )
        )


def test_work_discloses_only_closed_safe_limitations() -> None:
    # Running work has hit no limitation, and the vocabulary an operational
    # surface may draw one from stays closed and content-free.
    assert _claimed(_binding()).limitations == ()
    assert all(
        "identity" not in item.value
        or item is ReenrichmentLimitation.NO_AUTONOMOUS_IDENTITY_MUTATION
        for item in ReenrichmentLimitation
    )


def test_the_old_merge_mutation_authority_no_longer_exists() -> None:
    assert not hasattr(EntityReenrichmentService, "after_merge")


def test_every_governing_trigger_has_a_reachable_mutation_registration() -> None:
    reached = {
        trigger for triggers in TRIGGERS_BY_MUTATION_CAPABILITY.values() for trigger in triggers
    }
    assert (
        reached | _DIRECT_SPECIALIZED_TRIGGERS
        == set(ReenrichmentTrigger) - _VERSION_OBSERVER_TRIGGERS
    )
    assert all(capability.count(".") >= 1 for capability in TRIGGERS_BY_MUTATION_CAPABILITY)


def test_every_mapped_mutation_can_register_its_trigger_work() -> None:
    repository = _Repository()
    produced: set[ReenrichmentTrigger] = set()
    for ordinal, capability in enumerate(TRIGGERS_BY_MUTATION_CAPABILITY, start=1):
        work = register_mutation_reenrichment(
            repository,
            principal_id=PRINCIPAL,
            capability=capability,
            cause_record_id=f"audit_{ordinal:016x}",
            policy_version="ri-v0.2",
            at=WHEN,
        )
        produced.update(item.binding.trigger for item in work)
    assert produced == {
        trigger for triggers in TRIGGERS_BY_MUTATION_CAPABILITY.values() for trigger in triggers
    }


def test_source_observer_registers_only_an_exact_version_advance() -> None:
    repository = _Repository()
    assert (
        register_source_version_observation(
            repository,
            principal_id=PRINCIPAL,
            source_object_id=SOURCE_OBJECT,
            source_version_id=SOURCE_VERSION,
            policy_version="policy-v1",
            at=WHEN,
        )
        is None
    )
    assert (
        register_source_version_observation(
            repository,
            principal_id=PRINCIPAL,
            source_object_id=SOURCE_OBJECT,
            source_version_id=SOURCE_VERSION,
            policy_version="policy-v2",
            at=WHEN,
        )
        is None
    )
    changed_version = "ver_bbbb0002bbbb0002"
    work = register_source_version_observation(
        repository,
        principal_id=PRINCIPAL,
        source_object_id=SOURCE_OBJECT,
        source_version_id=changed_version,
        policy_version="policy-v2",
        at=WHEN,
    )
    assert work is not None
    assert work.binding.trigger is ReenrichmentTrigger.SOURCE_VERSION_CHANGE
    assert work.binding.subjects == (
        ReenrichmentSubject(ReenrichmentSubjectKind.SOURCE_OBJECT, SOURCE_OBJECT, changed_version),
        ReenrichmentSubject(
            ReenrichmentSubjectKind.SOURCE_VERSION, changed_version, changed_version
        ),
    )
    watermark_key = f"source_{hashlib.sha256(SOURCE_OBJECT.encode()).hexdigest()[:40]}"
    assert work.binding.input_versions == (BindingVersion(watermark_key, changed_version),)
    assert work.binding.producer_versions == (
        BindingVersion("source_pipeline", "sources.fetch.v1"),
    )


def test_producer_observer_excludes_policy_and_registers_exact_advance() -> None:
    repository = _Repository()
    arguments = {
        "principal_id": PRINCIPAL,
        "proposal_id": PROPOSAL,
        "proposal_version": "proposed",
        "method": "rules",
        "method_version": "pipeline-v1",
        "model_id": None,
        "model_version": None,
        "at": WHEN,
    }
    assert (
        register_producer_version_observation(repository, policy_version="policy-v1", **arguments)
        is None
    )
    assert (
        register_producer_version_observation(repository, policy_version="policy-v2", **arguments)
        is None
    )
    work = register_producer_version_observation(
        repository,
        policy_version="policy-v2",
        **{**arguments, "method_version": "pipeline-v2"},
    )
    assert work is not None
    assert work.binding.trigger is ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE
    assert work.binding.subjects == (
        ReenrichmentSubject(ReenrichmentSubjectKind.PROPOSAL, PROPOSAL, "proposed"),
    )
    assert len(work.binding.producer_versions) == 1
    assert work.binding.producer_versions[0].key == "entity_proposal"


def test_generic_mutation_binding_is_current_and_reaches_the_apply_callback() -> None:
    repository = _Repository()
    (work,) = register_mutation_reenrichment(
        repository,
        principal_id=PRINCIPAL,
        capability="entities.update",
        cause_record_id="emut_aaaa0001aaaa0001",
        policy_version="policy-v1",
        at=WHEN,
    )
    current = _SqlEquivalentCurrent(repository)
    assert assess_currency(work.binding, current).is_current
    applied: list[str] = []
    currency = EntityReenrichmentService(repository).apply_claimed(
        _as_claimed(repository, work),
        owner="worker_01",
        current=current,
        apply=lambda _binding, key: applied.append(key),
        at=WHEN,
    )
    assert currency.is_current
    assert applied == [work.binding.binding_sha256]


def test_generic_mutation_binding_stales_when_policy_or_producer_advances() -> None:
    repository = _Repository()
    (work,) = register_mutation_reenrichment(
        repository,
        principal_id=PRINCIPAL,
        capability="entities.update",
        cause_record_id="emut_aaaa0001aaaa0001",
        policy_version="policy-v1",
        at=WHEN,
    )
    repository.versions[("producer", "relationship_intelligence")] = "v-next"
    repository.versions[("policy", "current")] = "policy-v2"
    reasons = assess_currency(work.binding, _SqlEquivalentCurrent(repository)).reasons
    assert reasons == (
        StaleBindingReason.POLICY_VERSION_CHANGED,
        StaleBindingReason.PRODUCER_VERSION_CHANGED,
    )


def test_source_binding_is_current_then_a_new_source_version_makes_it_stale() -> None:
    repository = _Repository()
    register_source_version_observation(
        repository,
        principal_id=PRINCIPAL,
        source_object_id=SOURCE_OBJECT,
        source_version_id=SOURCE_VERSION,
        policy_version="policy-v1",
        at=WHEN,
    )
    second = "ver_bbbb0002bbbb0002"
    work = register_source_version_observation(
        repository,
        principal_id=PRINCIPAL,
        source_object_id=SOURCE_OBJECT,
        source_version_id=second,
        policy_version="policy-v1",
        at=WHEN,
    )
    assert work is not None
    subjects = {
        (ReenrichmentSubjectKind.SOURCE_OBJECT, SOURCE_OBJECT): second,
        (ReenrichmentSubjectKind.SOURCE_VERSION, second): second,
    }
    current = _SqlEquivalentCurrent(repository, subjects=subjects)
    applied: list[str] = []
    currency = EntityReenrichmentService(repository).apply_claimed(
        _as_claimed(repository, work),
        owner="worker_01",
        current=current,
        apply=lambda _binding, key: applied.append(key),
        at=WHEN,
    )
    assert currency.is_current
    assert applied == [work.binding.binding_sha256]
    third = "ver_cccc0003cccc0003"
    register_source_version_observation(
        repository,
        principal_id=PRINCIPAL,
        source_object_id=SOURCE_OBJECT,
        source_version_id=third,
        policy_version="policy-v1",
        at=WHEN,
    )
    subjects[(ReenrichmentSubjectKind.SOURCE_OBJECT, SOURCE_OBJECT)] = third
    reasons = assess_currency(
        work.binding, _SqlEquivalentCurrent(repository, subjects=subjects)
    ).reasons
    assert reasons == (
        StaleBindingReason.INPUT_VERSION_CHANGED,
        StaleBindingReason.SUBJECT_VERSION_CHANGED,
    )


def test_producer_binding_is_current_then_a_producer_advance_makes_it_stale() -> None:
    repository = _Repository()
    common = {
        "principal_id": PRINCIPAL,
        "proposal_id": PROPOSAL,
        "proposal_version": "proposed",
        "method": "rules",
        "model_id": None,
        "model_version": None,
        "policy_version": "policy-v1",
        "at": WHEN,
    }
    register_producer_version_observation(repository, method_version="v1", **common)
    work = register_producer_version_observation(repository, method_version="v2", **common)
    assert work is not None
    current = _SqlEquivalentCurrent(
        repository,
        subjects={(ReenrichmentSubjectKind.PROPOSAL, PROPOSAL): "proposed"},
    )
    applied: list[str] = []
    currency = EntityReenrichmentService(repository).apply_claimed(
        _as_claimed(repository, work),
        owner="worker_01",
        current=current,
        apply=lambda _binding, key: applied.append(key),
        at=WHEN,
    )
    assert currency.is_current
    assert applied == [work.binding.binding_sha256]
    current.subjects[(ReenrichmentSubjectKind.PROPOSAL, PROPOSAL)] = "accepted"
    assert assess_currency(work.binding, current).reasons == (
        StaleBindingReason.SUBJECT_VERSION_CHANGED,
    )
    current.subjects[(ReenrichmentSubjectKind.PROPOSAL, PROPOSAL)] = "proposed"
    register_producer_version_observation(repository, method_version="v3", **common)
    assert assess_currency(work.binding, current).reasons == (
        StaleBindingReason.PRODUCER_VERSION_CHANGED,
    )


def test_all_nine_triggers_are_covered_by_truthful_mutations_and_exact_observers() -> None:
    mutation_triggers = {
        trigger for triggers in TRIGGERS_BY_MUTATION_CAPABILITY.values() for trigger in triggers
    }
    assert mutation_triggers | _DIRECT_SPECIALIZED_TRIGGERS | _VERSION_OBSERVER_TRIGGERS == set(
        ReenrichmentTrigger
    )


@pytest.mark.parametrize("capability", tuple(TRIGGERS_BY_MUTATION_CAPABILITY))
def test_handler_attested_new_mutation_registers_once_and_replay_registers_zero(
    capability: str,
) -> None:
    repository = _Repository()
    created = _Result(
        payload={},
        disclosure=None,  # type: ignore[arg-type]
        reenrichment_cause_id="emut_aaaa0001aaaa0001",
    )
    replay_or_noop = _Result(payload={}, disclosure=None)  # type: ignore[arg-type]

    _register_reenrichment_result(
        repository,
        result=created,
        principal_id=PRINCIPAL,
        capability=capability,
        policy_version="ri-v0.2",
        at=WHEN,
    )
    assert len(repository.registered) == 1

    _register_reenrichment_result(
        repository,
        result=replay_or_noop,
        principal_id=PRINCIPAL,
        capability=capability,
        policy_version="ri-v0.2",
        at=WHEN,
    )
    assert len(repository.registered) == 1


def test_distinct_mutation_receipts_on_one_entity_register_distinct_work() -> None:
    repository = _Repository()
    for cause in ("emut_aaaa0001aaaa0001", "emut_bbbb0002bbbb0002"):
        _register_reenrichment_result(
            repository,
            result=_Result(
                payload={"entity_id": ENTITY},
                disclosure=None,  # type: ignore[arg-type]
                reenrichment_cause_id=cause,
            ),
            principal_id=PRINCIPAL,
            capability="entities.update",
            policy_version="ri-v0.2",
            at=WHEN,
        )
    assert len(repository.registered) == 2


def test_review_invalidated_success_has_no_reenrichment_effect() -> None:
    repository = _Repository()
    _register_reenrichment_result(
        repository,
        result=_Result(
            payload={"review_case_id": "rvw_aaaa0001aaaa0001", "result": "invalidated"},
            disclosure=None,  # type: ignore[arg-type]
        ),
        principal_id=PRINCIPAL,
        capability="review.decide",
        policy_version="ri-v0.2",
        at=WHEN,
    )
    assert repository.registered == {}


@pytest.mark.parametrize("field", ["input_versions", "producer_versions"])
def test_version_bindings_are_bounded_and_keys_are_unique(field: str) -> None:
    too_many = tuple(
        BindingVersion(f"version_{index}", "v1") for index in range(MAX_REENRICHMENT_VERSIONS + 1)
    )
    with pytest.raises(ValueError, match="bounded version sets"):
        _binding(**{field: too_many})
    with pytest.raises(ValueError, match="version key once"):
        _binding(
            **{
                field: (
                    BindingVersion("same", "v1"),
                    BindingVersion("same", "v2"),
                )
            }
        )


@pytest.mark.parametrize(
    ("method_name", "trigger"),
    [(trigger.value, trigger) for trigger in ReenrichmentTrigger],
)
def test_every_governing_trigger_has_a_load_bearing_production_caller(
    method_name: str, trigger: ReenrichmentTrigger
) -> None:
    repository = _Repository()
    caller = ProductionReenrichmentCaller(
        repository,
        principal_id=PRINCIPAL,
        policy_version="policy-v1",
    )
    method = getattr(caller, method_name)
    work = method(
        f"event_{trigger.value.replace('_', '')[:16]}00000000",
        (ReenrichmentSubject(ReenrichmentSubjectKind.PRINCIPAL, PRINCIPAL, "1"),),
        at=WHEN,
    )
    assert work.binding.trigger is trigger
    assert len(repository.registered) == 1
    assert repository.versions[("producer", "relationship_intelligence")]
    assert repository.versions[("policy", "current")] == "policy-v1"


def test_process_version_observation_registers_only_real_advances() -> None:
    repository = _Repository()
    first = ProductionReenrichmentCaller(
        repository,
        principal_id=PRINCIPAL,
        policy_version="policy-v1",
        producer_version="resolver-v1",
    )
    assert first.observe_process_versions(PRINCIPAL, cause="boot_aaaaaaaa", at=WHEN) == ()
    changed = ProductionReenrichmentCaller(
        repository,
        principal_id=PRINCIPAL,
        policy_version="policy-v2",
        producer_version="resolver-v2",
    )
    work = changed.observe_process_versions(PRINCIPAL, cause="boot_bbbbbbbb", at=WHEN)
    assert {item.binding.trigger for item in work} == {ReenrichmentTrigger.POLICY_CHANGE}


# ---- WP-05 / RI-P3-MED-001: a durable, truthful PARTIAL outcome -----------
#
# RI v0.2 section 27.5: "Partial processing never appears complete." The state
# vocabulary has to distinguish complete success, partial success, stale,
# retryable failure and terminal failure, and `limitations` has to carry what
# was actually persisted rather than the whole closed vocabulary.


def test_the_state_vocabulary_distinguishes_every_settled_outcome() -> None:
    assert set(ReenrichmentState) == {
        ReenrichmentState.QUEUED,
        ReenrichmentState.RUNNING,
        ReenrichmentState.SUCCEEDED,
        ReenrichmentState.PARTIAL,
        ReenrichmentState.STALE,
        ReenrichmentState.FAILED,
    }


def test_partial_work_is_terminal_and_never_reports_succeeded() -> None:
    partial = _terminal_work(
        ReenrichmentState.PARTIAL,
        limitations=(ReenrichmentLimitation.BOUNDED_SUBJECT_SET,),
    )
    assert partial.state is ReenrichmentState.PARTIAL
    assert partial.state is not ReenrichmentState.SUCCEEDED
    assert partial.state.value != ReenrichmentState.SUCCEEDED.value
    assert partial.completed_at is not None
    with pytest.raises(ValueError, match="terminal"):
        replace(partial, completed_at=None)


def test_partial_work_states_which_limitations_it_settled_under() -> None:
    with pytest.raises(ValueError, match="limitation"):
        _terminal_work(ReenrichmentState.PARTIAL, limitations=())


def test_only_partial_work_carries_limitations() -> None:
    for state in (
        ReenrichmentState.SUCCEEDED,
        ReenrichmentState.STALE,
        ReenrichmentState.FAILED,
    ):
        with pytest.raises(ValueError, match="limitation"):
            _terminal_work(
                state,
                limitations=(ReenrichmentLimitation.BOUNDED_SUBJECT_SET,),
            )


def test_limitations_are_the_persisted_set_and_not_the_whole_vocabulary() -> None:
    one = _terminal_work(
        ReenrichmentState.PARTIAL,
        limitations=(ReenrichmentLimitation.STABLE_EXTRACTION_REUSED,),
    )
    assert one.limitations == (ReenrichmentLimitation.STABLE_EXTRACTION_REUSED,)
    assert one.limitations != tuple(ReenrichmentLimitation)


def _terminal_work(
    state: ReenrichmentState,
    *,
    limitations: tuple[ReenrichmentLimitation, ...],
) -> ReenrichmentWork:
    return ReenrichmentWork(
        work_id="erwk_aaaa0001aaaa0001",
        binding=_binding(),
        state=state,
        attempt_count=1,
        max_attempts=3,
        created_at=WHEN - timedelta(minutes=1),
        updated_at=WHEN,
        completed_at=WHEN,
        stale_reasons=(
            (StaleBindingReason.POLICY_VERSION_CHANGED,) if state is ReenrichmentState.STALE else ()
        ),
        limitations=limitations,
    )


# ---- WP-04 / RI-P3-HIGH-001: which review decisions imply re-enrichment ----
#
# `review.decide` used to register CONTRADICTION_RESOLUTION for every committed
# decision, which every `Disposition` member and every
# `ReviewSubjectKind` value reach. RI v0.2 section 10.11 scopes a contradiction
# to conflicting *assertions* a reviewer chooses between; the repository's own
# `TRIGGERS_BY_MUTATION_CAPABILITY` sends only `entities.unresolved_mentions.resolve`
# there. The matrix below is the whole predicate: seventeen proposal kinds by
# eight dispositions, spelled out independently of the mapping under test.

_ACCEPTING = frozenset({Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT})

#: The state a decision of each disposition settles the proposal in.
_SETTLED_STATE: dict[Disposition, ProposalState] = {
    Disposition.ACCEPT: ProposalState.ACCEPTED,
    Disposition.CORRECT_AND_ACCEPT: ProposalState.CORRECTED_ACCEPTED,
    Disposition.REJECT: ProposalState.REJECTED,
    Disposition.DEFER: ProposalState.DEFERRED,
    Disposition.MARK_UNRESOLVED: ProposalState.UNRESOLVED,
    Disposition.REPROCESS: ProposalState.NEEDS_REVIEW,
    Disposition.ESCALATE: ProposalState.NEEDS_REVIEW,
    Disposition.INVALIDATE: ProposalState.INVALIDATED,
}

#: The trigger the *equivalent direct mutation* already registers, restated here
#: rather than imported, so the test disagrees with the implementation when the
#: implementation changes.
_EXPECTED_ACCEPTED_TRIGGER: dict[EntityProposalKind, ReenrichmentTrigger | None] = {
    EntityProposalKind.CREATE_ENTITY: None,
    EntityProposalKind.UPDATE_ENTITY: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.BIND_IDENTIFIER: None,
    EntityProposalKind.RETIRE_IDENTIFIER: None,
    EntityProposalKind.SUPERSEDE_IDENTIFIER: None,
    EntityProposalKind.RECORD_ALIAS: ReenrichmentTrigger.NEW_ALIAS,
    EntityProposalKind.RETIRE_ALIAS: ReenrichmentTrigger.NEW_ALIAS,
    EntityProposalKind.SUPERSEDE_ALIAS: ReenrichmentTrigger.NEW_ALIAS,
    EntityProposalKind.RECORD_ASSIGNMENT: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.REVISE_ASSIGNMENT: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.END_ASSIGNMENT: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.RECORD_RELATIONSHIP: ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    EntityProposalKind.REVISE_RELATIONSHIP: ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    EntityProposalKind.END_RELATIONSHIP: ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    EntityProposalKind.RESOLVE_MENTION: ReenrichmentTrigger.CONTRADICTION_RESOLUTION,
    EntityProposalKind.MERGE_ENTITIES: None,
    EntityProposalKind.SPLIT_IDENTITY: None,
}


def test_the_expected_matrix_covers_every_proposal_kind_and_disposition() -> None:
    assert set(_EXPECTED_ACCEPTED_TRIGGER) == set(EntityProposalKind)
    assert len(EntityProposalKind) == 17
    assert set(_SETTLED_STATE) == set(Disposition)
    assert len(Disposition) == 8


@pytest.mark.parametrize("kind", list(EntityProposalKind), ids=lambda item: item.value)
@pytest.mark.parametrize("disposition", list(Disposition), ids=lambda item: item.value)
def test_every_kind_by_disposition_registers_exactly_its_equivalent_trigger(
    kind: EntityProposalKind, disposition: Disposition
) -> None:
    trigger = reenrichment_trigger_for_review_decision(
        proposed_kind=kind,
        disposition=disposition,
        proposal_state=_SETTLED_STATE[disposition],
    )
    expected = _EXPECTED_ACCEPTED_TRIGGER[kind] if disposition in _ACCEPTING else None
    assert trigger == expected


def test_only_an_accepted_mention_resolution_reaches_contradiction_resolution() -> None:
    reaching = {
        (kind, disposition)
        for kind in EntityProposalKind
        for disposition in Disposition
        if reenrichment_trigger_for_review_decision(
            proposed_kind=kind,
            disposition=disposition,
            proposal_state=_SETTLED_STATE[disposition],
        )
        is ReenrichmentTrigger.CONTRADICTION_RESOLUTION
    }
    assert reaching == {
        (EntityProposalKind.RESOLVE_MENTION, Disposition.ACCEPT),
        (EntityProposalKind.RESOLVE_MENTION, Disposition.CORRECT_AND_ACCEPT),
    }


def test_an_unrelated_accept_registers_no_contradiction_work() -> None:
    for kind in (
        EntityProposalKind.RECORD_ALIAS,
        EntityProposalKind.UPDATE_ENTITY,
        EntityProposalKind.RECORD_RELATIONSHIP,
        EntityProposalKind.CREATE_ENTITY,
    ):
        assert (
            reenrichment_trigger_for_review_decision(
                proposed_kind=kind,
                disposition=Disposition.ACCEPT,
                proposal_state=ProposalState.ACCEPTED,
            )
            is not ReenrichmentTrigger.CONTRADICTION_RESOLUTION
        )


@pytest.mark.parametrize(
    ("disposition", "state"),
    [
        (Disposition.REJECT, ProposalState.REJECTED),
        (Disposition.INVALIDATE, ProposalState.INVALIDATED),
        (Disposition.DEFER, ProposalState.DEFERRED),
        (Disposition.MARK_UNRESOLVED, ProposalState.UNRESOLVED),
        (Disposition.REPROCESS, ProposalState.NEEDS_REVIEW),
        (Disposition.ESCALATE, ProposalState.NEEDS_REVIEW),
    ],
    ids=lambda item: getattr(item, "value", item),
)
def test_no_non_accepting_disposition_registers_anything(
    disposition: Disposition, state: ProposalState
) -> None:
    for kind in EntityProposalKind:
        assert (
            reenrichment_trigger_for_review_decision(
                proposed_kind=kind, disposition=disposition, proposal_state=state
            )
            is None
        )


def test_accepting_merge_or_split_through_review_registers_nothing() -> None:
    # Accepting either through review executes nothing: it emits an
    # `EntityIdentityCorrectionHandoff` in `OPERATOR_PREVIEW_REQUIRED`
    # (`tests/unit/test_entity_proposal_review.py`). The later operator
    # `entities.merge` / `entities.split` registers CORRECTED_IDENTITY itself.
    for kind in (EntityProposalKind.MERGE_ENTITIES, EntityProposalKind.SPLIT_IDENTITY):
        for disposition in _ACCEPTING:
            assert (
                reenrichment_trigger_for_review_decision(
                    proposed_kind=kind,
                    disposition=disposition,
                    proposal_state=_SETTLED_STATE[disposition],
                )
                is None
            )


def test_an_accepting_disposition_that_did_not_land_accepted_registers_nothing() -> None:
    for state in (
        ProposalState.NEEDS_REVIEW,
        ProposalState.INVALIDATED,
        ProposalState.SUPERSEDED,
        ProposalState.REJECTED,
    ):
        assert (
            reenrichment_trigger_for_review_decision(
                proposed_kind=EntityProposalKind.RESOLVE_MENTION,
                disposition=Disposition.ACCEPT,
                proposal_state=state,
            )
            is None
        )


def test_a_review_subject_that_is_not_an_entity_proposal_registers_nothing() -> None:
    # `capture_proposal`, `goodnotes_region` and `relationship_memory` reach
    # `_review_decide` with `entity_case is None`, so there is no proposed kind
    # and therefore no equivalent direct mutation to name.
    for disposition in Disposition:
        assert (
            reenrichment_trigger_for_review_decision(
                proposed_kind=None,
                disposition=disposition,
                proposal_state=_SETTLED_STATE[disposition],
            )
            is None
        )
