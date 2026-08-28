"""Durable RI re-enrichment bindings and pre-application currency gate."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.entity_reenrichment import (
    BindingVersion,
    EntityReenrichmentService,
    ReenrichmentBinding,
    ReenrichmentLimitation,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
    ReenrichmentWork,
    StaleBindingReason,
    assess_currency,
)

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY = "ent_aaaa0001aaaa0001"
ALIAS = "eals_aaaa0001aaaa0001"
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

    def mark_stale(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        reasons: Sequence[StaleBindingReason],
        at: datetime,
    ) -> bool:
        assert principal_id == PRINCIPAL and owner == "worker_01" and at == WHEN
        self.stale.append((work_id, tuple(reasons)))
        return True

    def complete(self, principal_id: str, work_id: str, *, owner: str, at: datetime) -> bool:
        assert principal_id == PRINCIPAL and owner == "worker_01" and at == WHEN
        self.completed.append(work_id)
        return True


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
        apply=applied.append,
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
        apply=lambda held: applied.append(held.binding_sha256),
        at=WHEN,
    )
    assert currency.is_current
    assert applied == [binding.binding_sha256]
    assert repository.completed == ["erwk_aaaa0001aaaa0001"]


def test_expired_claim_never_invokes_the_applier() -> None:
    binding = _binding()
    repository = _Repository()
    applied: list[ReenrichmentBinding] = []
    expired = replace(_claimed(binding), lease_expires_at=WHEN)

    with pytest.raises(ValueError, match="live claim"):
        EntityReenrichmentService(repository).apply_claimed(
            expired,
            owner="worker_01",
            current=_Current(binding),
            apply=applied.append,
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
