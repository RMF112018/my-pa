"""CRL-WP-03 CP-CRL-07: `capture.archive` and `capture.restore` on the wire (CRL-AC-D6).

Compact and canonical normalization produce the same command. A remote key is a
digest of the payload, so the same intent stamps the same key and a changed
reason stamps another. Unknown properties, a boolean revision, and a delete
alias are refused. The reason stays out of `repr`.
"""

from __future__ import annotations

from my_pa.adapters.mcp.chatllm_gateway import WRITE_TOOL, prepare_compact_call
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.commands import ArchiveCapture, RestoreCapture
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.capture.lifecycle import CaptureLifecycleOperation
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import DenialReason, PolicyRequest, evaluate
from my_pa.domain.source.registry import issue_identifier

PRINCIPAL = issue_identifier(IdKind.PRINCIPAL)
CAPTURE = issue_identifier(IdKind.CAPTURE)
REASON = "  Owner withdrew the note  "
PAYLOAD = {
    "capture_id": CAPTURE,
    "expected_lifecycle_revision": 0,
    "reason": REASON,
}
CANONICAL = {**PAYLOAD, "idempotency_key": "lifecycle-contract-key"}


def _envelope(payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-capture-lifecycle-contract",
        "purpose": Purpose.CAPTURE_AUTHORING.value,
        "principal_id": PRINCIPAL,
        "requested_at": "2026-10-01T12:00:00Z",
        "payload": payload,
    }


def test_compact_and_canonical_normalization_agree() -> None:
    allowed = frozenset(capability.value for capability in Capability)
    for capability in (Capability.CAPTURE_ARCHIVE, Capability.CAPTURE_RESTORE):
        document = _envelope(CANONICAL)
        canonical, nested = prepare_compact_call(
            WRITE_TOOL,
            {"capability": capability.value, "arguments": document},
            allowed_canonical=allowed,
        )
        assert canonical == capability.value
        assert nested is not None
        direct = normalize(capability.value, document)
        compact = normalize(canonical, nested)
        assert compact == direct
        assert isinstance(compact[1], ArchiveCapture | RestoreCapture)
        assert compact[1].reason == "Owner withdrew the note"
        assert compact[1].expected_lifecycle_revision == 0
        assert "reason" not in repr(compact[1])


def test_remote_key_stamping_is_deterministic_and_intent_sensitive() -> None:
    principal = Principal(PRINCIPAL, PrincipalKind.OPERATOR, authenticated=True)

    def stamp(payload: dict[str, object]) -> str:
        composed = compose_remote_arguments(
            capability_name=Capability.CAPTURE_ARCHIVE.value,
            arguments={"payload": payload},
            principal=principal,
            grants=None,
        )
        return str(composed["payload"]["idempotency_key"])

    first = stamp(PAYLOAD)
    assert first == stamp(dict(PAYLOAD))
    changed = dict(PAYLOAD)
    changed["reason"] = "A different owner statement"
    assert first != stamp(changed)
    stamped = dict(PAYLOAD)
    stamped["idempotency_key"] = first
    command = normalize(Capability.CAPTURE_ARCHIVE.value, _envelope(stamped))[1]
    assert isinstance(command, ArchiveCapture)
    assert command.idempotency_key == first
    supplied = dict(PAYLOAD)
    supplied["idempotency_key"] = "caller-supplied-key"
    try:
        compose_remote_arguments(
            capability_name=Capability.CAPTURE_ARCHIVE.value,
            arguments={"payload": supplied},
            principal=principal,
            grants=None,
        )
    except InvalidRequestError:
        pass
    else:
        raise AssertionError("a caller-supplied remote key was accepted")


def test_unknown_properties_and_a_boolean_revision_are_refused() -> None:
    extra = dict(CANONICAL)
    extra["delete"] = True
    try:
        normalize(Capability.CAPTURE_ARCHIVE.value, _envelope(extra))
    except InvalidRequestError:
        pass
    else:
        raise AssertionError("an unknown property was accepted")
    boolean = dict(CANONICAL)
    boolean["expected_lifecycle_revision"] = True
    try:
        ArchiveCapture(
            capture_id=CAPTURE,
            expected_lifecycle_revision=True,  # type: ignore[arg-type]
            idempotency_key="lifecycle-bool",
            reason=REASON,
        )
    except InvalidRequestError as error:
        assert error.safe_details == (SafeDetail.EXPECTED_LIFECYCLE_REVISION,)
    else:
        raise AssertionError("a boolean revision was accepted on the command")
    try:
        normalize(Capability.CAPTURE_RESTORE.value, _envelope(boolean))
    except InvalidRequestError as error:
        assert error.safe_details == (SafeDetail.EXPECTED_LIFECYCLE_REVISION,)
    else:
        raise AssertionError("a boolean revision was accepted on the wire")


def test_no_delete_alias_or_hard_delete_field_is_accepted() -> None:
    assert "capture.delete" not in {capability.value for capability in Capability}
    try:
        normalize("capture.delete", _envelope(CANONICAL))
    except InvalidRequestError:
        pass
    else:
        raise AssertionError("capture.delete was accepted")
    assert "delete" not in ArchiveCapture.__dataclass_fields__
    assert "delete" not in RestoreCapture.__dataclass_fields__


def test_archive_and_restore_are_destructive_scopeless_authoring_writes() -> None:
    principal = Principal(PRINCIPAL, PrincipalKind.OPERATOR, authenticated=True)
    for capability in (Capability.CAPTURE_ARCHIVE, Capability.CAPTURE_RESTORE):
        assert permitted_purposes(capability) == frozenset({Purpose.CAPTURE_AUTHORING})
        assert is_write_capability(capability)
        assert is_destructive_capability(capability)
        allowed = evaluate(
            PolicyRequest(
                principal=principal,
                purpose=Purpose.CAPTURE_AUTHORING,
                capability=capability,
                classification=Classification.PRIVATE_LOCAL,
            )
        )
        assert allowed.allowed
        named = evaluate(
            PolicyRequest(
                principal=principal,
                purpose=Purpose.CAPTURE_AUTHORING,
                capability=capability,
                classification=Classification.PRIVATE_LOCAL,
                requested_source_ids=frozenset({issue_identifier(IdKind.SOURCE)}),
            )
        )
        assert not named.allowed
        assert named.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_reason_bounds_refuse_blank_and_overlong_text_without_echoing_it() -> None:
    sentinel = "SENTINEL-lifecycle-reason"
    for reason in ("   ", sentinel * 40):
        try:
            ArchiveCapture(
                capture_id=CAPTURE,
                expected_lifecycle_revision=0,
                idempotency_key="lifecycle-reason-bound",
                reason=reason,
            )
        except InvalidRequestError as error:
            assert error.safe_details == (SafeDetail.REASON,)
            assert sentinel not in str(error)
        else:
            raise AssertionError(f"reason {reason!r} was accepted")
    kept = RestoreCapture(
        capture_id=CAPTURE,
        expected_lifecycle_revision=2,
        idempotency_key="lifecycle-reason-trim",
        reason=f"  {sentinel}  ",
    )
    assert kept.reason == sentinel
    assert kept.capability is Capability.CAPTURE_RESTORE
    assert CaptureLifecycleOperation.RESTORE.value == "restore"
