"""Durable RI re-enrichment bindings and pre-application currency gate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
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
    register_mutation_reenrichment,
    register_producer_version_observation,
    register_source_version_observation,
)
from my_pa.application.service import _register_reenrichment_result, _Result

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY = "ent_aaaa0001aaaa0001"
ALIAS = "eals_aaaa0001aaaa0001"
SOURCE_OBJECT = "obj_aaaa0001aaaa0001"
SOURCE_VERSION = "ver_aaaa0001aaaa0001"
PROPOSAL = "eprp_aaaa0001aaaa0001"
WHEN = datetime(2026, 8, 28, 12, tzinfo=UTC)


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
        work = _claimed(_binding())
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
    ) -> object:
        del principal_id, at
        previous = self.versions.get((namespace, key))
        self.versions[(namespace, key)] = version

        class _Observation:
            changed = previous is not None and previous != version

        return _Observation()


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
    limitations = _claimed(_binding()).limitations
    assert limitations == tuple(ReenrichmentLimitation)
    assert all(
        "identity" not in item.value
        or item is ReenrichmentLimitation.NO_AUTONOMOUS_IDENTITY_MUTATION
        for item in limitations
    )


def test_the_old_merge_mutation_authority_no_longer_exists() -> None:
    assert not hasattr(EntityReenrichmentService, "after_merge")


def test_every_governing_trigger_has_a_reachable_mutation_registration() -> None:
    reached = {
        trigger for triggers in TRIGGERS_BY_MUTATION_CAPABILITY.values() for trigger in triggers
    }
    assert reached == set(ReenrichmentTrigger) - {
        ReenrichmentTrigger.SOURCE_VERSION_CHANGE,
        ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE,
    }
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
    assert produced == set(ReenrichmentTrigger) - {
        ReenrichmentTrigger.SOURCE_VERSION_CHANGE,
        ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE,
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
    assert work.binding.input_versions == (BindingVersion("source_version", changed_version),)
    assert work.binding.producer_versions == (
        BindingVersion("source_pipeline", "sources.fetch.v1"),
    )


def test_producer_observer_excludes_policy_and_registers_exact_advance() -> None:
    repository = _Repository()
    arguments = {
        "principal_id": PRINCIPAL,
        "proposal_id": PROPOSAL,
        "proposal_version": "1",
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
        ReenrichmentSubject(ReenrichmentSubjectKind.PROPOSAL, PROPOSAL, "1"),
    )
    assert work.binding.producer_versions == (
        BindingVersion("proposal_method", "rules"),
        BindingVersion("proposal_pipeline", "pipeline-v2"),
    )


def test_all_nine_triggers_are_covered_by_truthful_mutations_and_exact_observers() -> None:
    mutation_triggers = {
        trigger for triggers in TRIGGERS_BY_MUTATION_CAPABILITY.values() for trigger in triggers
    }
    assert mutation_triggers | {
        ReenrichmentTrigger.SOURCE_VERSION_CHANGE,
        ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE,
    } == set(ReenrichmentTrigger)


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
