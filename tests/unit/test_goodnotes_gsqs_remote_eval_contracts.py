"""Contracts for GSQS ChatLLM remote-eval session identity and schemas."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_CAPTURE_CONFLICT,
    ERROR_DISCLOSURE_UNCERTAIN,
    ERROR_EVAL_DISABLED,
    ERROR_FORBIDDEN_SCOPE,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_INVALID_ANALYZER_OUTPUT,
    ERROR_INVALID_TRANSITION,
    ERROR_LEASE_CONFLICT,
    ERROR_LEASE_EXPIRED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_RASTER_INTEGRITY_FAILURE,
    ERROR_RESULT_TOO_LARGE,
    ERROR_SESSION_BLOCKED,
    ERROR_SESSION_EXPIRED,
    ERROR_SESSION_NOT_IN_PROGRESS,
    ERROR_STATE_INTEGRITY_FAILURE,
    ERROR_UNAUTHENTICATED,
    EVENT_DISCLOSED_TO_TRANSPORT,
    EVENT_NOT_DISCLOSED,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    MANIFEST_FORBIDDEN_KEYS,
    REMOTE_EVAL_ERROR_CODES,
    SCHEMA_CAPTURE_ENTRY_V1,
    SCHEMA_DISCLOSURE_JOURNAL_V2,
    SCHEMA_TERMINAL_RECEIPT_V1,
    ManifestCase,
    RemoteEvalMode,
    SessionManifest,
    build_remote_eval_session,
    compute_session_identity_sha256,
    manifest_public_dict,
    remote_eval_canonical_dumps,
    remote_eval_canonical_sha256,
    session_identity_payload,
)


def _hex(label: str) -> str:
    return remote_eval_canonical_sha256(label)


def _session(**changes: object) -> object:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    kwargs: dict[str, object] = {
        "session_id": "sess-1",
        "mode": RemoteEvalMode.SYNTHETIC_CANARY,
        "authorization_id": "auth-1",
        "principal_id": "principal-1",
        "created_at": now,
        "expires_at": now + timedelta(hours=2),
        "repository_owner": "RMF112018",
        "repository_name": "my-pa",
        "repository_commit_sha": "abc123",
        "repository_tree_sha": "def456",
        "evaluator_id": "goodnotes-gsqs-independent",
        "evaluator_version": "1.1",
        "evaluator_behavior_sha256": _hex("eval"),
        "corpus_version": "synthetic-b-1",
        "public_manifest_sha256": _hex("public"),
        "combined_identity_sha256": _hex("combined"),
        "case_count": 73,
        "case_order_sha256": _hex("order"),
        "analyzer_id": "chatllm-goodnotes-semantic",
        "analyzer_version": "sit-1.0",
        "semantic_prompt_sha256": _hex("semantic"),
        "conversation_prompt_sha256": _hex("conversation"),
        "model_selection_label": "route-llm",
    }
    kwargs.update(changes)
    return build_remote_eval_session(**kwargs)  # type: ignore[arg-type]


def test_canonical_dump_sorted_keys_compact_separators_and_non_ascii() -> None:
    dumped = remote_eval_canonical_dumps({"b": 1, "a": "café"})
    assert dumped == '{"a":"café","b":1}'
    assert "\\u" not in dumped
    assert dumped == '{"a":"café","b":1}'


def test_canonical_dump_rejects_nan() -> None:
    with pytest.raises(ValueError):
        remote_eval_canonical_dumps({"x": float("nan")})


def test_canonical_sha256_is_lowercase_hex() -> None:
    digest = remote_eval_canonical_sha256({"k": "v"})
    assert len(digest) == 64
    assert digest == digest.lower()
    assert set(digest) <= set("0123456789abcdef")


def test_session_identity_excludes_its_own_hash_and_is_stable() -> None:
    session = _session()
    payload = session_identity_payload(session)
    assert "session_identity_sha256" not in payload
    assert session.session_identity_sha256 == compute_session_identity_sha256(session)
    again = _session()
    assert again.session_identity_sha256 == session.session_identity_sha256


def test_mutating_any_identity_field_changes_the_hash() -> None:
    session = _session()
    mutated = replace(session, analyzer_id="other-analyzer")
    assert compute_session_identity_sha256(mutated) != session.session_identity_sha256
    mutated_prompt = replace(session, semantic_prompt_sha256=_hex("other-prompt"))
    assert compute_session_identity_sha256(mutated_prompt) != session.session_identity_sha256


def test_phase_c_mode_exists() -> None:
    assert RemoteEvalMode.PHASE_C.value == "PHASE_C"
    assert RemoteEvalMode.SYNTHETIC_CANARY.value == "SYNTHETIC_CANARY"


def test_error_codes_are_complete() -> None:
    required = {
        ERROR_EVAL_DISABLED,
        ERROR_UNAUTHENTICATED,
        ERROR_FORBIDDEN_SCOPE,
        ERROR_NO_ACTIVE_SESSION,
        ERROR_SESSION_EXPIRED,
        ERROR_SESSION_BLOCKED,
        ERROR_SESSION_NOT_IN_PROGRESS,
        ERROR_INVALID_TRANSITION,
        ERROR_LEASE_CONFLICT,
        ERROR_LEASE_EXPIRED,
        ERROR_INVALID_ANALYZER_OUTPUT,
        ERROR_CAPTURE_CONFLICT,
        ERROR_RASTER_INTEGRITY_FAILURE,
        ERROR_DISCLOSURE_UNCERTAIN,
        ERROR_RESULT_TOO_LARGE,
        ERROR_STATE_INTEGRITY_FAILURE,
        ERROR_INTERNAL_FAIL_CLOSED,
    }
    assert required == REMOTE_EVAL_ERROR_CODES
    assert len(REMOTE_EVAL_ERROR_CODES) == 17


def test_session_dataclass_is_frozen() -> None:
    session = _session()
    with pytest.raises(FrozenInstanceError):
        session.session_id = "nope"  # type: ignore[misc]


def test_manifest_serialization_omits_gold_path_and_label_keys() -> None:
    session = _session()
    manifest = SessionManifest(
        schema_version="gsqs-remote-eval-session-manifest-v1",
        session_id=session.session_id,
        session_identity_sha256=session.session_identity_sha256,
        cases=(
            ManifestCase(
                ordinal=1,
                case_id="syn-b-001",
                content_sha256=_hex("c1"),
                byte_length=12,
                staged_filename="syn-b-001.png",
            ),
        ),
    )
    payload = manifest_public_dict(manifest)
    dumped = remote_eval_canonical_dumps(payload)
    for key in MANIFEST_FORBIDDEN_KEYS:
        assert key not in dumped
        assert key not in payload
        for case in payload["cases"]:  # type: ignore[index]
            assert key not in case  # type: ignore[operator]
    assert "staged_filename" in dumped
    assert "content_sha256" in dumped
    assert "gold" not in dumped
    assert "path" not in dumped
    assert "label" not in dumped


def test_capture_entry_schema_identity() -> None:
    assert SCHEMA_CAPTURE_ENTRY_V1 == "gsqs-remote-eval-capture-entry-v1"


def test_terminal_receipt_schema_identity() -> None:
    assert SCHEMA_TERMINAL_RECEIPT_V1 == "gsqs-remote-eval-terminal-receipt-v1"


def test_disclosure_journal_v2_schema_and_event_names() -> None:
    assert SCHEMA_DISCLOSURE_JOURNAL_V2 == "gsqs-b0-disclosure-journal-v2"
    assert EVENT_OUTBOUND_ATTEMPT_STARTED == "OUTBOUND_ATTEMPT_STARTED"
    assert EVENT_DISCLOSED_TO_TRANSPORT == "DISCLOSED_TO_TRANSPORT"
    assert EVENT_NOT_DISCLOSED == "NOT_DISCLOSED"
