"""Phase-A authenticated public contract for scheduled GoodNotes pull clients."""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.commands import (
    CompleteGoodNotesPull,
    GetGoodNotesPullStatus,
    PullGoodNotesWork,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.goodnotes_pull_orchestration import (
    GoodNotesCompletionReceipt,
    GoodNotesPullAssignment,
    GoodNotesPullBatch,
    PullAssignment,
    PullBatch,
    PullCompletionReceipt,
    public_completion_receipts,
    public_pull_batch,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.goodnotes.models import GoodNotesPageWork, issue_stable_id
from my_pa.domain.identity.operation import Capability, is_write_capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyRequest, evaluate

PRINCIPAL_ID = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
ASSIGNMENT_ID = hashlib.sha256(b"assignment").hexdigest()


def _principal(*, authenticated: bool = True) -> Principal:
    return Principal(PRINCIPAL_ID, PrincipalKind.GATEWAY, authenticated=authenticated)


def _remote(capability: Capability, payload: dict[str, object]) -> dict[str, object]:
    return compose_remote_arguments(
        capability_name=capability.value,
        arguments={"payload": payload},
        principal=_principal(),
        grants=frozenset({(capability, None)}),
        issue_id=lambda _kind: "corr_aaaaaaaaaaaaaaaaaaaaaaaa",
    )


def test_public_commands_admit_only_caller_owned_scheduling_references() -> None:
    assert {field.name for field in dataclasses.fields(PullGoodNotesWork)} == {
        "batch_size",
        "cursor",
    }
    assert {field.name for field in dataclasses.fields(CompleteGoodNotesPull)} == {"assignment_ids"}
    assert not dataclasses.fields(GetGoodNotesPullStatus)

    _, pull = normalize(
        Capability.GOODNOTES_PULL.value,
        _remote(Capability.GOODNOTES_PULL, {"batch_size": 2}),
    )
    _, complete = normalize(
        Capability.GOODNOTES_COMPLETE.value,
        _remote(Capability.GOODNOTES_COMPLETE, {"assignment_ids": [ASSIGNMENT_ID]}),
    )
    _, status = normalize(
        Capability.GOODNOTES_STATUS.value,
        _remote(Capability.GOODNOTES_STATUS, {}),
    )
    assert pull == PullGoodNotesWork(batch_size=2)
    assert complete == CompleteGoodNotesPull(assignment_ids=(ASSIGNMENT_ID,))
    assert status == GetGoodNotesPullStatus()


@pytest.mark.parametrize(
    "field",
    (
        "principal_id",
        "client_id",
        "completion_id",
        "context_id",
        "run_id",
        "page_version_id",
        "content_sha256",
        "result_sha256",
        "request_fingerprint",
        "idempotency_key",
    ),
)
def test_remote_control_plane_refuses_caller_supplied_server_identity(field: str) -> None:
    with pytest.raises(InvalidRequestError):
        _remote(Capability.GOODNOTES_PULL, {"batch_size": 1, field: "forged"})
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=Capability.GOODNOTES_COMPLETE.value,
            arguments={field: "forged", "payload": {"assignment_ids": [ASSIGNMENT_ID]}},
            principal=_principal(),
            grants=frozenset({(Capability.GOODNOTES_COMPLETE, None)}),
        )


def test_pull_and_completion_write_but_status_has_separate_observation_authority() -> None:
    assert permitted_purposes(Capability.GOODNOTES_PULL) == {Purpose.GOODNOTES_PULL}
    assert permitted_purposes(Capability.GOODNOTES_COMPLETE) == {Purpose.GOODNOTES_PULL}
    assert permitted_purposes(Capability.GOODNOTES_STATUS) == {Purpose.GOODNOTES_PULL_OBSERVATION}
    assert is_write_capability(Capability.GOODNOTES_PULL)
    assert is_write_capability(Capability.GOODNOTES_COMPLETE)
    assert not is_write_capability(Capability.GOODNOTES_STATUS)

    denied = evaluate(
        PolicyRequest(
            principal=_principal(),
            purpose=Purpose.GOODNOTES_PULL_OBSERVATION,
            capability=Capability.GOODNOTES_COMPLETE,
            classification=Classification.PRIVATE_LOCAL,
        )
    )
    allowed = evaluate(
        PolicyRequest(
            principal=_principal(),
            purpose=Purpose.GOODNOTES_PULL_OBSERVATION,
            capability=Capability.GOODNOTES_STATUS,
            classification=Classification.PRIVATE_LOCAL,
        )
    )
    assert denied.allowed is False
    assert allowed.allowed is True and allowed.policy_version == POLICY_VERSION


def test_public_results_remove_principal_client_and_completion_private_state() -> None:
    work = GoodNotesPageWork(
        run_id=issue_stable_id("gnrun", "public-contract"),
        page_version_id=issue_stable_id("gnver", "public-contract"),
        principal_id=PRINCIPAL_ID,
        content_sha256=hashlib.sha256(b"content").hexdigest(),
    )
    internal_assignment = PullAssignment(
        assignment_id=ASSIGNMENT_ID,
        client_id="authenticated-client",
        context_id="server-context",
        work=work,
        attempt=1,
    )
    batch = public_pull_batch(PullBatch(assignments=(internal_assignment,), next_cursor="cursor"))
    receipt = public_completion_receipts(
        (
            PullCompletionReceipt(
                completion_id=hashlib.sha256(b"completion").hexdigest(),
                assignment_id=ASSIGNMENT_ID,
                idempotency_key="server-key",
                request_fingerprint=hashlib.sha256(b"request").hexdigest(),
                result_sha256=hashlib.sha256(b"result").hexdigest(),
                replayed=True,
            ),
        )
    )

    assert isinstance(batch, GoodNotesPullBatch)
    assert isinstance(batch.assignments[0], GoodNotesPullAssignment)
    assert isinstance(receipt[0], GoodNotesCompletionReceipt)
    assignment_fields = {field.name for field in dataclasses.fields(batch.assignments[0])}
    receipt_fields = {field.name for field in dataclasses.fields(receipt[0])}
    assert {"principal_id", "client_id", "context_id"}.isdisjoint(assignment_fields)
    assert {"idempotency_key", "request_fingerprint", "result_sha256"}.isdisjoint(receipt_fields)
