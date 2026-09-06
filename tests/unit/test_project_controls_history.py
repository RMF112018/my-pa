"""Unit tests for the PC-CM-IMP-WP02 Constraint mutation receipts.

These mirror, field for field, the CHECK constraints plan §C.7 and §C.8 place on
`knowledge.project_constraint_history` and `knowledge.constraint_category_history`,
so a receipt the database would refuse is refused here first, with a stable
`code` a caller can act on rather than an `IntegrityError`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.project_controls.history import (
    MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS,
    MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS,
    ConstraintCategoryHistoryEntry,
    ConstraintCategoryMutationOperation,
    ConstraintHistoryEntry,
    ConstraintHistoryError,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
PROJECT_ID = "prj_aaaa0001aaaa0001aaaa"
CATEGORY_ID = "ccat_aaaa0001aaaa0001aaaa"
CONSTRAINT_ID = "cst_aaaa0001aaaa0001aaaa"
HISTORY_ID = "chst_aaaa0001aaaa0001aaaa"
CATEGORY_HISTORY_ID = "cchst_aaaa0001aaaa0001aaaa"
REVISION_ID = "crev_aaaa0001aaaa0001aaaa"
CORRELATION_ID = "corr_aaaa0001aaaa0001aaaa"
DIGEST = "a" * 64
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _entry(**overrides: object) -> ConstraintHistoryEntry:
    fields: dict[str, object] = {
        "history_id": HISTORY_ID,
        "principal_id": PRINCIPAL_ID,
        "constraint_id": CONSTRAINT_ID,
        "operation": ConstraintMutationOperation.UPDATE,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "outcome": ConstraintMutationOutcome.APPLIED,
        "before_version": 1,
        "after_version": 2,
        "occurred_at": T0,
        "recorded_at": T0,
        "revision_id": REVISION_ID,
    }
    fields.update(overrides)
    return ConstraintHistoryEntry(**fields)  # type: ignore[arg-type]


def _category_entry(**overrides: object) -> ConstraintCategoryHistoryEntry:
    fields: dict[str, object] = {
        "history_id": CATEGORY_HISTORY_ID,
        "principal_id": PRINCIPAL_ID,
        "project_id": PROJECT_ID,
        "category_id": CATEGORY_ID,
        "operation": ConstraintCategoryMutationOperation.CREATE,
        "actor": ConstraintMutationActor.ASSISTANT,
        "outcome": ConstraintMutationOutcome.APPLIED,
        "before_version": 0,
        "after_version": 1,
        "occurred_at": T0,
        "recorded_at": T0,
    }
    fields.update(overrides)
    return ConstraintCategoryHistoryEntry(**fields)  # type: ignore[arg-type]


def test_the_three_vocabularies_are_this_plane_s_own_and_closed() -> None:
    assert [member.value for member in ConstraintMutationOperation] == [
        "close",
        "create",
        "publish",
        "reopen",
        "transition",
        "update",
        "void",
    ]
    assert {member.value for member in ConstraintMutationActor} == {
        "assistant",
        "principal",
        "system",
    }
    assert {member.value for member in ConstraintMutationOutcome} == {
        "applied",
        "no_op",
        "rejected",
    }
    assert {member.value for member in ConstraintCategoryMutationOperation} == {
        "archive",
        "create",
        "update",
    }


def test_a_constraint_receipt_records_its_identities_and_normalises_its_times() -> None:
    entry = _entry(
        project_id=PROJECT_ID,
        correlation_id=CORRELATION_ID,
        occurred_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
    )
    assert entry.constraint_id == CONSTRAINT_ID
    assert entry.occurred_at.tzinfo is UTC
    assert entry.recorded_at == T0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("history_id", "cst_aaaa0001aaaa0001aaaa"),
        ("principal_id", "prj_aaaa0001aaaa0001aaaa"),
        ("constraint_id", "ccat_aaaa0001aaaa0001aaaa"),
        ("project_id", "prn_aaaa0001aaaa0001aaaa0001"),
        ("revision_id", "chst_aaaa0001aaaa0001aaaa"),
        ("correlation_id", "cst_aaaa0001aaaa0001aaaa"),
    ],
)
def test_every_identifier_is_checked_for_its_own_kind(field: str, value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        _entry(**{field: value})


def test_an_applied_mutation_advances_the_version_it_recorded() -> None:
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(before_version=2, after_version=2)
    assert refusal.value.code == "constraint_history_applied_without_advance"


@pytest.mark.parametrize(
    "outcome", [ConstraintMutationOutcome.NO_OP, ConstraintMutationOutcome.REJECTED]
)
def test_an_unapplied_mutation_records_no_version_change(
    outcome: ConstraintMutationOutcome,
) -> None:
    entry = _entry(outcome=outcome, before_version=3, after_version=3, revision_id=None)
    assert entry.after_version == entry.before_version
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(outcome=outcome, before_version=3, after_version=4, revision_id=None)
    assert refusal.value.code == "constraint_history_unapplied_advanced"


def test_a_before_version_is_never_negative() -> None:
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(before_version=-1, after_version=0)
    assert refusal.value.code == "constraint_history_before_version_negative"


def test_an_applied_mutation_names_its_revision_and_only_an_applied_one_does() -> None:
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(revision_id=None)
    assert refusal.value.code == "constraint_history_revision_pairing"
    with pytest.raises(ConstraintHistoryError) as second:
        _entry(
            outcome=ConstraintMutationOutcome.NO_OP,
            before_version=1,
            after_version=1,
            revision_id=REVISION_ID,
        )
    assert second.value.code == "constraint_history_revision_pairing"


def test_only_a_rejected_mutation_carries_a_failure_reason() -> None:
    rejected = _entry(
        outcome=ConstraintMutationOutcome.REJECTED,
        before_version=1,
        after_version=1,
        revision_id=None,
        safe_failure_reason="version_conflict",
    )
    assert rejected.safe_failure_reason == "version_conflict"
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(safe_failure_reason="version_conflict")
    assert refusal.value.code == "constraint_history_reason_without_rejection"


def test_a_failure_reason_is_bounded_and_non_blank() -> None:
    def rejected(reason: str) -> ConstraintHistoryEntry:
        return _entry(
            outcome=ConstraintMutationOutcome.REJECTED,
            before_version=1,
            after_version=1,
            revision_id=None,
            safe_failure_reason=reason,
        )

    with pytest.raises(ConstraintHistoryError) as blank:
        rejected("   ")
    assert blank.value.code == "constraint_history_reason_blank"
    with pytest.raises(ConstraintHistoryError) as long:
        rejected("x" * (MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS + 1))
    assert long.value.code == "constraint_history_reason_too_long"


@pytest.mark.parametrize("key", ["short", "a" * 129, "has space", "no/slashes/here"])
def test_an_idempotency_key_is_bounded_and_opaque(key: str) -> None:
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(idempotency_key=key)
    assert refusal.value.code == "constraint_history_idempotency_key_malformed"
    assert _entry(idempotency_key="a" * 8).idempotency_key == "a" * 8
    assert _entry(idempotency_key="A-b_" * 32).idempotency_key == "A-b_" * 32


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "z" * 64, ""])
def test_a_request_digest_is_a_lowercase_sha256(digest: str) -> None:
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(request_digest=digest)
    assert refusal.value.code == "constraint_history_request_digest_malformed"
    assert _entry(request_digest=DIGEST).request_digest == DIGEST


def test_client_context_is_a_bounded_label_and_never_a_request_body() -> None:
    with pytest.raises(ConstraintHistoryError) as blank:
        _entry(client_context="  ")
    assert blank.value.code == "constraint_history_client_context_blank"
    with pytest.raises(ConstraintHistoryError) as long:
        _entry(client_context="x" * (MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS + 1))
    assert long.value.code == "constraint_history_client_context_too_long"


def test_a_receipt_carries_no_payload_field_at_all() -> None:
    """CM-BE-AC-067: there is nowhere for a request body to be stored."""
    forbidden = {"payload", "body", "request", "prompt", "message", "arguments", "raw"}
    assert forbidden.isdisjoint(ConstraintHistoryEntry.__dataclass_fields__)
    assert forbidden.isdisjoint(ConstraintCategoryHistoryEntry.__dataclass_fields__)


def test_a_receipt_refuses_a_vocabulary_member_from_another_plane() -> None:
    with pytest.raises(ConstraintHistoryError) as refusal:
        _entry(operation="update")
    assert refusal.value.code == "constraint_history_operation_unknown"
    with pytest.raises(ConstraintHistoryError) as actor:
        _entry(actor="principal")
    assert actor.value.code == "constraint_history_actor_unknown"
    with pytest.raises(ConstraintHistoryError) as outcome:
        _entry(outcome="applied")
    assert outcome.value.code == "constraint_history_outcome_unknown"


def test_a_category_receipt_is_always_project_bound_and_names_no_revision() -> None:
    entry = _category_entry()
    assert entry.project_id == PROJECT_ID
    assert "revision_id" not in ConstraintCategoryHistoryEntry.__dataclass_fields__
    with pytest.raises(InvalidIdentifierError):
        _category_entry(project_id="prn_aaaa0001aaaa0001aaaa0001")


def test_a_category_receipt_shares_the_version_and_safe_field_rules() -> None:
    with pytest.raises(ConstraintHistoryError) as advance:
        _category_entry(before_version=1, after_version=1)
    assert advance.value.code == "constraint_history_applied_without_advance"
    with pytest.raises(ConstraintHistoryError) as reason:
        _category_entry(safe_failure_reason="prefix_locked")
    assert reason.value.code == "constraint_history_reason_without_rejection"
    with pytest.raises(ConstraintHistoryError) as key:
        _category_entry(idempotency_key="tiny")
    assert key.value.code == "constraint_history_idempotency_key_malformed"


def test_a_category_receipt_refuses_a_constraint_operation() -> None:
    with pytest.raises(ConstraintHistoryError) as refusal:
        _category_entry(operation=ConstraintMutationOperation.PUBLISH)
    assert refusal.value.code == "constraint_category_history_operation_unknown"
